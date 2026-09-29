"""CLI per popolare/ispezionare il registro per-comune (data-live/registro/).

Riusa `leggi_connettore` (treasureiq.connettore) per fare il lavoro vero: non
scrape, non re-implementa nulla — chiama il connettore già esistente e legge
quel che il connettore stesso ha già scritto nello store (`registro._da_store`).

Persistenza: `data-live/` è un bind mount di docker-compose (vedi
compose.yml) — i record scritti qui sopravvivono a `docker compose down`/`up`
e a `make rebuild`. `make backup` è la cintura extra sopra questa garanzia,
non l'unica.

Uso:
    python -m treasureiq.registro_cli scan [--coperti|--da-censimento|--tutti|ISTAT...]
                                             [--only-missing] [--delay SEC] [--limit N]
    python -m treasureiq.registro_cli sweep [--coperti|--da-censimento|--tutti|ISTAT...]
                                             [--db PATH] [--aderenza] [--only-missing]
                                             [--delay SEC] [--limit N] [--lavoratori N]
    python -m treasureiq.registro_cli list

`sweep` fa censimento (storico.db) + registro (data-live) per lo stesso set
in un solo run — vedi `_fase_censimento`/`_esegui_registro`. `scan` fa solo il
registro. `sweep` scrive storico.db: va lanciato con un mount scrivibile
(`make sweep`), non in `docker compose exec` dove `/data` è read-only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from treasureiq.catalog import SnapshotStore, persist_shadow_snapshots
from treasureiq.connettore import leggi_connettore
from treasureiq.integration import DATA_DIR, load_enti
from treasureiq.municipality_registry import (
    FrameInvalidError,
    FrameIOError,
    MunicipalityRecord,
    get_registry,
)
from treasureiq.registro import LIVE_DIR, _da_store
import treasureiq.sonda_live as sonda_live
from treasureiq.sonda_live import comune_per_codice
from treasureiq import bootstrap as bootstrap_sel

#: Piattaforme che `leggi_connettore` sa davvero leggere oggi. Tenere in
#: sincrono con i dispatch in connettore.py — aggiungerne una lì senza
#: aggiornare questo set fa sì che --da-censimento continui a ignorarla.
#: NB: il censimento (storico.db) etichetta la famiglia eGov col fingerprint
#: "hgate" (CMS Halley), NON "egov" — il connettore la riclassifica a "egov"
#: solo alla lettura profonda. Qui serve il nome del CENSIMENTO, altrimenti
#: --da-censimento salta i ~956 comuni hgate.
#: NB2: il fingerprint "peopleweb" conflaziona due vendor (SoluzioniPA
#: OpenWeb + Siscom PeopleWeb): il dispatch li discrimina dall'HTML home e
#: instrada a openweb.py / peopleweb.py. Il censimento li etichetta entrambi
#: "peopleweb", quindi basta quella voce per coprirli tutti e 1124.
_LEGGIBILI = {
    "municipium",
    "egov",
    "hgate",
    "peopleweb",
    # famiglia WordPress-AgID (D-09, wordpress_agid.py): stessi censimento
    # label del rilevamento, il connettore le legge tutte con lo stesso adapter.
    "wp_design_comuni",
    "wordpress_generico",
    "comunibootstrapitalia",
    # ComWeb (ePublic) + OpenPA (Maggioli): scraper dedicati (comweb.py /
    # openpa.py), rotte AgID + argomenti confermate su comuni reali.
    "comweb",
    "openpa",
}


def _comuni_coperti() -> list[str]:
    return sorted(load_enti().keys())


def _registry_or_exit():
    path = sonda_live.COMUNI_ISTAT_PATH
    try:
        return get_registry(path)
    except FrameIOError as exc:
        raise SystemExit(
            f"comuni-istat.json assente ({path}): esegui 'make frame-nazionale'."
        ) from exc
    except FrameInvalidError as exc:
        codici = ", ".join(sorted({issue.code for issue in exc.report.blocking}))
        raise SystemExit(f"comuni-istat.json invalido ({path}): {codici}") from exc


def _comuni_tutti() -> list[str]:
    registry = _registry_or_exit()
    return sorted(record.codice_istat for record in registry.frame.tutti())


def _comuni_da_censimento(db: Path) -> list[str]:
    if not db.exists():
        raise SystemExit(
            f"storico.db assente ({db}): esegui prima 'make scan-nazionale' per popolarlo."
        )
    from treasureiq.storico import apri

    segnaposto = ",".join("?" * len(_LEGGIBILI))
    with apri(db) as conn:
        righe = conn.execute(
            f"SELECT DISTINCT codice_istat FROM portale_snapshot WHERE piattaforma IN ({segnaposto})",
            tuple(sorted(_LEGGIBILI)),
        ).fetchall()
    return sorted(r["codice_istat"] for r in righe)


def _select_comuni(args: argparse.Namespace) -> list[str]:
    if args.istat:
        return list(args.istat)
    if args.tutti:
        print("ATTENZIONE: --tutti scansiona ~7896 comuni, la maggior parte darà esito vuoto.",
              file=sys.stderr)
        return _comuni_tutti()
    if args.da_censimento:
        return _comuni_da_censimento(args.db)
    return _comuni_coperti()


def _scansiona_uno(istat: str) -> tuple[str, str]:
    """Scansiona un comune, ritorna (stato, riga-di-log). Mai un'eccezione:
    un comune rotto non deve fermare il batch (continue-on-error)."""
    comune = comune_per_codice(istat)
    nome = comune.nome if comune else istat
    try:
        esito = leggi_connettore(istat, usa_cache=False)
    except Exception as exc:  # noqa: BLE001 — un comune che eccepisce non ferma il batch
        return "errore", f"{istat} {nome} — errore: {exc}"
    if esito is None:
        return "vuoto", f"{istat} {nome} — vuoto"
    record = _da_store(istat)
    if record is None:
        return "vuoto", f"{istat} {nome} — vuoto"
    logo = "si" if record.logo_b64 else "no"
    n_uffici = len(record.uffici_snapshot)
    return "ok", f"{istat} {nome} — ok uffici={n_uffici} logo={logo}"


def _selezione_valida(args: argparse.Namespace) -> bool:
    """False se il chiamante ha mescolato ISTAT espliciti coi flag di selezione."""
    return not (args.istat and (args.coperti or args.da_censimento or args.tutti))


def _filtra_only_missing(comuni: list[str]) -> list[str]:
    return [c for c in comuni if _da_store(c) is None]


def _esegui_shadow(
    istat: str, *, store: SnapshotStore, measurement_id: str
) -> tuple[str, str]:
    """Translate an already cached v0 map; never starts a new map probe."""
    from treasureiq import mappa_connettore as mappa_module

    mappa = mappa_module._da_cache(istat)
    if mappa is None:
        return "shadow_skipped", f"{istat} — shadow saltato: mappa v0 assente"
    events = persist_shadow_snapshots(
        mappa,
        store=store,
        measurement_id=measurement_id,
        measured_at=datetime.now(timezone.utc),
    )
    drift = len(events)
    return "shadow_ok", f"{istat} — shadow snapshot ok drift={drift}"


def _esegui_registro(
    comuni: list[str],
    *,
    delay: float,
    shadow_store: SnapshotStore | None = None,
    shadow_measurement_id: str | None = None,
) -> dict[str, int]:
    """Fase registro: un `leggi_connettore` per comune, continue-on-error.

    Riusata da `cmd_scan` (registro da solo) e `cmd_sweep` (dopo il
    censimento), sullo stesso set di comuni.
    """
    contatori = {
        "ok": 0,
        "vuoto": 0,
        "errore": 0,
        "con_logo": 0,
        "shadow_ok": 0,
        "shadow_skipped": 0,
        "shadow_error": 0,
    }
    for indice, istat in enumerate(comuni):
        stato, riga = _scansiona_uno(istat)
        contatori[stato] += 1
        if stato == "ok":
            record = _da_store(istat)
            if record is not None and record.logo_b64:
                contatori["con_logo"] += 1
        print(riga, file=sys.stderr)
        if shadow_store is not None and shadow_measurement_id is not None:
            try:
                shadow_stato, shadow_riga = _esegui_shadow(
                    istat, store=shadow_store, measurement_id=shadow_measurement_id
                )
            except Exception as exc:  # noqa: BLE001 — shadow non deve fermare v0
                shadow_stato = "shadow_error"
                shadow_riga = f"{istat} — shadow errore: {exc}"
            contatori[shadow_stato] += 1
            print(shadow_riga, file=sys.stderr)
        if delay and indice < len(comuni) - 1:
            time.sleep(delay)
    return contatori


def cmd_scan(args: argparse.Namespace) -> int:
    if not _selezione_valida(args):
        print("errore: usa i codici ISTAT oppure un flag di selezione, non insieme.",
              file=sys.stderr)
        return 2

    comuni = _select_comuni(args)
    if args.only_missing:
        comuni = _filtra_only_missing(comuni)
    if args.limit is not None:
        comuni = comuni[: args.limit]

    shadow_store, shadow_id = _shadow_config(args)
    contatori = _esegui_registro(
        comuni,
        delay=args.delay,
        shadow_store=shadow_store,
        shadow_measurement_id=shadow_id,
    )
    print(
        f"scansionati {len(comuni)} · con-record {contatori['ok']} · "
        f"con-logo {contatori['con_logo']} · vuoti {contatori['vuoto']} · "
        f"errori {contatori['errore']}",
        file=sys.stderr,
    )
    return 0


# --------------------------------------------------------------------------- #
# bootstrap: canary-first enrolment of eligible, uninitialised comuni
# --------------------------------------------------------------------------- #
#: Exit codes distinct so an operator (or a wrapper script) can tell apart a
#: clean run, per-comune errors, and a deliberate stop.
BOOTSTRAP_OK = 0
BOOTSTRAP_ERRORI = 1
BOOTSTRAP_STOP = 3


def _connettore_inizializzati() -> set[str]:
    """ISTAT codes that already hold a data-live connettore record.

    This is what "initialised" means for the refresh loop (and for the
    monitoring dashboard): the presence of ``data-live/connettore/<cod>.json``,
    not a registro entry.
    """
    conn_dir = LIVE_DIR / "connettore"
    if not conn_dir.exists():
        return set()
    return {percorso.stem for percorso in conn_dir.glob("*.json")}


def _bootstrap_stop_path(checkpoint: Path) -> Path:
    """Sibling stop-file: ``bootstrap.json`` -> ``bootstrap.stop``."""
    return checkpoint.with_suffix(".stop")


class _CheckpointInvalido(ValueError):
    """A checkpoint file exists but is corrupt or structurally invalid.

    Raised instead of degrading to empty state: a resume must never silently
    restart from scratch and overwrite prior progress — the data-live records
    already created for the completed comuni would be lost from the ledger.
    """


def _lista_stringhe(dati: dict, chiave: str) -> list[str]:
    """Validated ``list[str]`` for one checkpoint field (empty if absent)."""
    grezzo = dati.get(chiave) or []
    if not isinstance(grezzo, list):
        raise _CheckpointInvalido(f"campo '{chiave}' non e' una lista")
    return [c for c in grezzo if isinstance(c, str)]


def _bootstrap_carica_checkpoint(
    checkpoint: Path,
) -> tuple[list[str], set[str], set[str], list[str], str | None, int]:
    """Return ``(selezione, arruolati, vuoti, errori, avviato_il, totale)``.

    Three disjoint outcome categories, never merged:
      * ``arruolati`` — an ``ok`` read that wrote a data-live record; the only
        ones the refresh worker will pick up.
      * ``vuoti`` — a successful read with NO record written; terminal for now,
        skipped on --resume, and NEVER counted as initialised.
      * ``errori`` — a failed read; retried on --resume.

    Raises ``_CheckpointInvalido`` if the file is unreadable, not a JSON
    object, or missing the frozen ``selezione`` list. No silent fallback to
    empty state: the caller stops (exit 2) rather than recompute a fresh
    selection and clobber the record of what was already initialised.
    """
    try:
        dati = json.loads(checkpoint.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _CheckpointInvalido(f"illeggibile o non JSON: {exc}") from exc
    if not isinstance(dati, dict):
        raise _CheckpointInvalido("il contenuto non e' un oggetto JSON")
    selezione = dati.get("selezione")
    if not isinstance(selezione, list) or not all(isinstance(c, str) for c in selezione):
        raise _CheckpointInvalido("campo 'selezione' mancante o non valido")
    arruolati = set(_lista_stringhe(dati, "arruolati"))
    vuoti = set(_lista_stringhe(dati, "vuoti"))
    errori = list(dict.fromkeys(_lista_stringhe(dati, "errori")))  # dedup, keep order
    avviato = dati.get("avviato_il")
    if not isinstance(avviato, str):
        avviato = None
    totale = dati.get("totale_candidati")
    if not isinstance(totale, int) or totale < 0:
        totale = len(selezione)
    return selezione, arruolati, vuoti, errori, avviato, totale


def _bootstrap_salva_checkpoint(
    checkpoint: Path,
    *,
    avviato_il: str,
    selezione: list[str],
    arruolati: set[str],
    vuoti: set[str],
    errori: list[str],
    totale_candidati: int,
) -> None:
    payload = {
        "avviato_il": avviato_il,
        "aggiornato_il": datetime.now(timezone.utc).isoformat(),
        "totale_candidati": totale_candidati,
        # Frozen selection: on --resume it is authoritative, never recomputed,
        # so a canary/lotto stays the SAME set even after some comuni have
        # already been initialised (and thus dropped from a fresh selection).
        "selezione": list(selezione),
        # Three disjoint categories — arruolati are the only enrolled comuni;
        # vuoti are terminal-for-now and out of the refresh; errori are retried.
        "arruolati": sorted(arruolati),
        "vuoti": sorted(vuoti),
        "errori": sorted(errori),
    }
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
    provvisorio.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    provvisorio.replace(checkpoint)


def cmd_bootstrap(args: argparse.Namespace) -> int:
    if args.delay < 0:
        print("errore: --delay deve essere >= 0.", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("errore: --limit deve essere >= 1.", file=sys.stderr)
        return 2
    if args.max_per_run is not None and args.max_per_run < 1:
        print("errore: --max-per-run deve essere >= 1.", file=sys.stderr)
        return 2
    if args.max_per_run is not None and args.checkpoint is None:
        print("errore: --max-per-run richiede --checkpoint.", file=sys.stderr)
        return 2
    if args.per_piattaforma < 1:
        print("errore: --per-piattaforma deve essere >= 1.", file=sys.stderr)
        return 2

    catalog_dir = args.catalog

    avviato_il = datetime.now(timezone.utc).isoformat()
    arruolati: set[str] = set()
    vuoti: set[str] = set()
    errori: list[str] = []
    selezione: list[str]
    totale_candidati: int
    resuming = False

    if args.checkpoint is not None and args.checkpoint.exists():
        # A checkpoint on disk: only --resume may touch it. Anything wrong with
        # its contents stops the run (exit 2, no fetch) — never a silent restart
        # that would recompute a different selection and clobber the ledger.
        if not args.resume:
            print(
                f"errore: checkpoint {args.checkpoint} esiste gia'. Usa --resume "
                "per continuarlo, o indica un percorso nuovo.",
                file=sys.stderr,
            )
            return 2
        try:
            selezione, arruolati, vuoti, errori, avviato_prec, totale_candidati = (
                _bootstrap_carica_checkpoint(args.checkpoint)
            )
        except _CheckpointInvalido as exc:
            print(
                f"errore: checkpoint {args.checkpoint} corrotto o invalido ({exc}). "
                "Nessun fetch eseguito; correggi o rimuovi il file.",
                file=sys.stderr,
            )
            return 2
        if avviato_prec:
            avviato_il = avviato_prec
        resuming = True
    elif args.resume and args.checkpoint is not None:
        # --resume but nothing to resume from: refuse rather than start a fresh
        # run under a resume flag (the operator expected an existing ledger).
        print(
            f"errore: --resume ma il checkpoint {args.checkpoint} non esiste. "
            "Nessun fetch eseguito.",
            file=sys.stderr,
        )
        return 2

    if not resuming:
        # Fresh run: compute the selection ONCE and freeze it in the checkpoint.
        coda = set(_comuni_da_censimento(args.db))
        gia_init = _connettore_inizializzati()
        candidati = bootstrap_sel.seleziona(catalog_dir, coda, gia_init)
        if args.piattaforma:
            candidati = [c for c in candidati if c[1] == args.piattaforma]
        totale_candidati = len(candidati)
        if args.canary:
            selezione = bootstrap_sel.canary(candidati, per_piattaforma=args.per_piattaforma)
            if args.limit is not None:
                print("nota: --canary ignora --limit.", file=sys.stderr)
        else:
            selezione = bootstrap_sel.lotto(candidati, args.limit)

    # Skip terminal outcomes: arruolati (record written) and vuoti (successful
    # read, no record — terminal for now, out of the refresh). Errored comuni
    # are NOT skipped, so a --resume retries them.
    da_fare = [c for c in selezione if c not in arruolati and c not in vuoti]
    da_fare_run = da_fare[:args.max_per_run]

    plat_map = bootstrap_sel.mappa_eleggibili(catalog_dir)
    conteggio_piattaforme = Counter(plat_map.get(c, "?") for c in selezione)
    print(
        f"bootstrap: candidati totali {totale_candidati} · selezione {len(selezione)} · "
        f"arruolati {len(arruolati)} · vuoti {len(vuoti)} · errori {len(errori)} · "
        f"da fare {len(da_fare)} · piattaforme {dict(conteggio_piattaforme)}"
        + (" · RESUME" if resuming else ""),
        file=sys.stderr,
    )

    if args.dry_run:
        for codice in da_fare_run:
            print(f"DRY {codice}", file=sys.stderr)
        print(f"dry-run: {len(da_fare_run)} comuni verrebbero inizializzati (nessuna scrittura).",
              file=sys.stderr)
        return BOOTSTRAP_OK

    stop_path = _bootstrap_stop_path(args.checkpoint) if args.checkpoint is not None else None

    # Freeze the selection to disk BEFORE the first fetch, so a --resume always
    # continues the ORIGINAL selection even if the run is stopped after zero
    # completed comuni (blocker: a fresh selection would then drift).
    if args.checkpoint is not None and not resuming:
        _bootstrap_salva_checkpoint(
            args.checkpoint,
            avviato_il=avviato_il,
            selezione=selezione,
            arruolati=arruolati,
            vuoti=vuoti,
            errori=errori,
            totale_candidati=totale_candidati,
        )

    fermato = False
    ok_run = vuoti_run = err_run = 0
    for indice, istat in enumerate(da_fare_run):
        if stop_path is not None and stop_path.exists():
            print(f"stop richiesto ({stop_path}): interrompo prima di {istat}.",
                  file=sys.stderr)
            fermato = True
            break
        stato, riga = _scansiona_uno(istat)
        print(riga, file=sys.stderr)
        if stato == "ok":
            # A record was written: enrolled. The refresh worker will pick it up.
            arruolati.add(istat)
            vuoti.discard(istat)
            errori = [e for e in errori if e != istat]
            ok_run += 1
        elif stato == "vuoto":
            # Successful read but NO record: terminal for now, out of the refresh
            # and never counted as initialised. NOT arruolato.
            vuoti.add(istat)
            errori = [e for e in errori if e != istat]
            vuoti_run += 1
        else:  # "errore": keep OUT of arruolati/vuoti so --resume retries it
            err_run += 1
            if istat not in errori:
                errori.append(istat)
        if args.checkpoint is not None:
            _bootstrap_salva_checkpoint(
                args.checkpoint,
                avviato_il=avviato_il,
                selezione=selezione,
                arruolati=arruolati,
                vuoti=vuoti,
                errori=errori,
                totale_candidati=totale_candidati,
            )
        if args.delay and indice < len(da_fare_run) - 1:
            time.sleep(args.delay)

    print(
        f"bootstrap fatto: arruolati +{ok_run} (tot {len(arruolati)}) · "
        f"vuoti +{vuoti_run} (tot {len(vuoti)}) · errori-run {err_run} · "
        f"errori-cumulativi {len(errori)}"
        + (" · FERMATO" if fermato else ""),
        file=sys.stderr,
    )
    if fermato:
        return BOOTSTRAP_STOP
    return BOOTSTRAP_ERRORI if errori else BOOTSTRAP_OK


def _anagrafe_comuni() -> dict[str, MunicipalityRecord]:
    """Anagrafe ISTAT indicizzata per codice — serve sia a costruire i dict
    comune per `censisci_molti`, sia come lookup provincia/regione/sito per
    `_registra`."""
    registry = _registry_or_exit()
    return {record.codice_istat: record for record in registry.frame.tutti()}


def _fase_censimento(comuni_istat: list[str], args: argparse.Namespace) -> tuple[int, int]:
    """Fase 1 di sweep: misura i comuni e scrive storico.db (riusa il motore
    di `treasureiq.ingest.censimento`, nessun re-scraping qui).

    Ritorna (misurati, saltati-per-resume).
    """
    from datetime import datetime, timezone

    from treasureiq.ingest.censimento import _gia_registrati, _registra, censisci_molti

    anagrafe_records = _anagrafe_comuni()
    anagrafe = {codice: record.model_dump() for codice, record in anagrafe_records.items()}
    oggi = datetime.now(timezone.utc).date()
    gia_fatti = _gia_registrati(args.db, oggi)
    da_misurare = [
        anagrafe[istat] for istat in comuni_istat if istat in anagrafe and istat not in gia_fatti
    ]
    saltati = len(comuni_istat) - len(da_misurare)
    if not da_misurare:
        return 0, saltati

    args.db.parent.mkdir(parents=True, exist_ok=True)
    measurement_at = datetime.now(timezone.utc)
    measurement_id = measurement_at.strftime("sweep-%Y%m%dT%H%M%SZ")
    catalog_output = args.catalog_output or args.db.parent / "catalog"
    try:
        censisci_molti(
            da_misurare,
            leggi_pagina=not args.tutti,
            lavoratori=args.lavoratori,
            misura_piattaforma=True,
            misura_aderenza=args.aderenza and not args.tutti,
            salva=lambda blocco: _registra(
                blocco,
                db=args.db,
                anagrafe=anagrafe,
                catalog_output=catalog_output,
                measurement_id=measurement_id,
                measured_at=measurement_at,
            ),
        )
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            f"storico.db non scrivibile ({args.db}): {exc}. "
            "Usa 'make sweep' (monta un volume scrivibile su /scrivibile), non "
            "'docker compose exec' dove /data è read-only."
        ) from exc
    return len(da_misurare), saltati


def cmd_sweep(args: argparse.Namespace) -> int:
    if not _selezione_valida(args):
        print("errore: usa i codici ISTAT oppure un flag di selezione, non insieme.",
              file=sys.stderr)
        return 2

    comuni = _select_comuni(args)
    if args.limit is not None:
        comuni = comuni[: args.limit]

    misurati, saltati = _fase_censimento(comuni, args)

    comuni_registro = _filtra_only_missing(comuni) if args.only_missing else comuni
    shadow_store, shadow_id = _shadow_config(args)
    contatori = _esegui_registro(
        comuni_registro,
        delay=args.delay,
        shadow_store=shadow_store,
        shadow_measurement_id=shadow_id,
    )

    print(
        f"CENSIMENTO: misurati {misurati} (saltati-resume {saltati}) · "
        f"REGISTRO: con-record {contatori['ok']} · con-logo {contatori['con_logo']} · "
        f"vuoti {contatori['vuoto']} · errori {contatori['errore']}",
        file=sys.stderr,
    )
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    cartella = LIVE_DIR / "registro"
    if not cartella.exists():
        print("nessun record: data-live/registro è vuota o assente.", file=sys.stderr)
        return 0

    con_logo = 0
    totale = 0
    for percorso in sorted(cartella.glob("*.json")):
        totale += 1
        record = _da_store(percorso.stem)
        if record is None:
            print(f"{percorso.stem} — store illeggibile", file=sys.stderr)
            continue
        logo = "si" if record.logo_b64 else "no"
        if record.logo_b64:
            con_logo += 1
        print(f"{record.codice_istat} {record.nome} logo={logo} {record.ultima_scansione}")

    print(f"totale {totale} · con-logo {con_logo}", file=sys.stderr)
    return 0


def _add_selezione_args(sub: argparse.ArgumentParser) -> None:
    """Flag di selezione set comuni, condivisi fra `scan` e `sweep`."""
    selezione = sub.add_mutually_exclusive_group()
    selezione.add_argument("--coperti", action="store_true",
                            help="I comuni coperti in data/enti.json (default).")
    selezione.add_argument("--da-censimento", action="store_true",
                            help="Comuni su piattaforme leggibili, letti da --db (data/storico.db).")
    selezione.add_argument("--tutti", action="store_true",
                            help="Tutti i comuni ISTAT. PESANTE, la maggior parte darà esito vuoto.")
    sub.add_argument("istat", nargs="*",
                      help="Codici ISTAT espliciti (mutuamente esclusivo coi flag sopra).")


def _add_shadow_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--shadow",
        action="store_true",
        help="In aggiunta a v0, persiste snapshot v1 dalla mappa già in cache (nessuna nuova sonda).",
    )
    sub.add_argument(
        "--shadow-output",
        type=Path,
        default=LIVE_DIR / "catalog-shadow",
        help="Directory degli snapshot shadow (default: data-live/catalog-shadow).",
    )
    sub.add_argument(
        "--shadow-measurement-id",
        default=None,
        help="ID rilevazione shadow; se assente viene generato per il comando.",
    )


def _shadow_config(args: argparse.Namespace) -> tuple[SnapshotStore | None, str | None]:
    if not args.shadow:
        return None, None
    measurement_id = args.shadow_measurement_id or datetime.now(timezone.utc).strftime(
        "shadow-%Y%m%dT%H%M%SZ"
    )
    return SnapshotStore(args.shadow_output), measurement_id


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.registro_cli",
        description="Popola/ispeziona il registro per-comune (data-live/registro/<istat>.json).",
    )
    sub = parser.add_subparsers(dest="comando")

    scan = sub.add_parser("scan", help="Scansiona comuni e scrive il registro (default).")
    _add_selezione_args(scan)
    _add_shadow_args(scan)
    scan.add_argument("--only-missing", action="store_true",
                       help="Salta i comuni già presenti in data-live/registro.")
    scan.add_argument("--delay", type=float, default=1.5,
                       help="Pausa in secondi tra un comune e il successivo (default 1.5).")
    scan.add_argument("--limit", type=int, default=None,
                       help="Ferma dopo N comuni (utile per test).")
    scan.add_argument("--db", type=Path, default=DATA_DIR / "storico.db",
                       help="Path a storico.db per --da-censimento (default data/storico.db).")
    scan.set_defaults(func=cmd_scan)

    sweep = sub.add_parser(
        "sweep",
        help="Censimento (storico.db) + registro (data-live) per lo stesso set, in un run.",
        description=(
            "Fase 1: misura i comuni (asse A/B, come treasureiq.ingest.censimento) e "
            "scrive storico.db. Fase 2: leggi_connettore sullo stesso set, scrive "
            "data-live/registro. storico.db va scritto con un mount scrivibile: usa "
            "'make sweep', non 'docker compose exec' dove /data è read-only."
        ),
    )
    _add_selezione_args(sweep)
    _add_shadow_args(sweep)
    sweep.add_argument("--db", type=Path, default=DATA_DIR / "storico.db",
                        help="Path a storico.db (default data/storico.db; con 'make sweep' "
                        "è /scrivibile/storico.db).")
    sweep.add_argument(
        "--catalog-output",
        type=Path,
        default=None,
        help="Directory snapshot catalogo (default: accanto a storico.db).",
    )
    sweep.add_argument("--aderenza", action="store_true",
                        help="Misura anche l'aderenza AgID (ignorata con --tutti).")
    sweep.add_argument("--only-missing", action="store_true",
                        help="Nella fase registro, salta i comuni già presenti in data-live/registro.")
    sweep.add_argument("--delay", type=float, default=1.5,
                        help="Pausa in secondi tra un comune e il successivo nella fase "
                             "registro (default 1.5).")
    sweep.add_argument("--limit", type=int, default=None,
                        help="Ferma dopo N comuni (utile per test).")
    sweep.add_argument("--lavoratori", type=int, default=6,
                        help="Concorrenza della fase censimento (default 6).")
    sweep.set_defaults(func=cmd_sweep)

    elenco = sub.add_parser("list", help="Elenca i record presenti nel registro (read-only).")
    elenco.set_defaults(func=cmd_list)

    boot = sub.add_parser(
        "bootstrap",
        help="Inizializza i comuni eleggibili mai inizializzati (canary-first). "
             "Scrive solo data-live; catalogo e storico.db restano invariati.",
    )
    boot.add_argument("--canary", action="store_true",
                      help="Seleziona --per-piattaforma comuni per ognuna delle piattaforme "
                           "eleggibili (default 2 x 5 = 10). Ignora --limit.")
    boot.add_argument("--per-piattaforma", type=int, default=2,
                      help="Comuni per piattaforma in modalita' --canary (default 2).")
    boot.add_argument("--limit", type=int, default=None,
                      help="Numero massimo di comuni da inizializzare in questo lotto.")
    boot.add_argument("--piattaforma", choices=sorted(bootstrap_sel.PIATTAFORME_CATALOGO_REFRESH),
                      help="Seleziona una sola piattaforma del catalogo nel nuovo checkpoint.")
    boot.add_argument("--max-per-run", type=int, default=None,
                      help="Tenta al massimo N comuni per esecuzione; richiede --checkpoint.")
    boot.add_argument("--delay", type=float, default=2.0,
                      help="Secondi di pausa fra un comune e l'altro (default 2.0).")
    boot.add_argument("--checkpoint", type=Path, default=None,
                      help="File JSON di avanzamento: aggiornato dopo ogni comune. "
                           "Il file gemello .stop, se creato, ferma il lotto.")
    boot.add_argument("--resume", action="store_true",
                      help="Riprende un checkpoint esistente saltando i comuni gia' completati.")
    boot.add_argument("--dry-run", action="store_true",
                      help="Stampa la selezione senza alcun fetch ne' scrittura.")
    boot.add_argument("--catalog", type=Path, default=DATA_DIR / "catalog",
                      help="Directory del catalogo (default data/catalog).")
    boot.add_argument("--db", type=Path, default=DATA_DIR / "storico.db",
                      help="Path a storico.db per la coda di censimento (default data/storico.db).")
    boot.set_defaults(func=cmd_bootstrap)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"scan", "sweep", "list", "bootstrap", "-h", "--help"}:
        argv = ["scan", *argv]
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.comando is None:
        args.comando = "scan"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
