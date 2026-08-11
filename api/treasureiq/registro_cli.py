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
from pathlib import Path

from treasureiq.connettore import leggi_connettore
from treasureiq.integration import DATA_DIR, load_enti
from treasureiq.registro import LIVE_DIR, _da_store
from treasureiq.sonda_live import COMUNI_ISTAT_PATH, comune_per_codice

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


def _comuni_tutti() -> list[str]:
    if not COMUNI_ISTAT_PATH.exists():
        raise SystemExit(
            f"comuni-istat.json assente ({COMUNI_ISTAT_PATH}): esegui 'make frame-nazionale'."
        )
    grezzo = json.loads(COMUNI_ISTAT_PATH.read_text("utf-8"))
    return sorted(r["codice_istat"] for r in grezzo)


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
    n_aree = len(record.servizi_snapshot)
    return "ok", f"{istat} {nome} — ok aree={n_aree} logo={logo}"


def _selezione_valida(args: argparse.Namespace) -> bool:
    """False se il chiamante ha mescolato ISTAT espliciti coi flag di selezione."""
    return not (args.istat and (args.coperti or args.da_censimento or args.tutti))


def _filtra_only_missing(comuni: list[str]) -> list[str]:
    return [c for c in comuni if _da_store(c) is None]


def _esegui_registro(comuni: list[str], *, delay: float) -> dict[str, int]:
    """Fase registro: un `leggi_connettore` per comune, continue-on-error.

    Riusata da `cmd_scan` (registro da solo) e `cmd_sweep` (dopo il
    censimento), sullo stesso set di comuni.
    """
    contatori = {"ok": 0, "vuoto": 0, "errore": 0, "con_logo": 0}
    for indice, istat in enumerate(comuni):
        stato, riga = _scansiona_uno(istat)
        contatori[stato] += 1
        if stato == "ok":
            record = _da_store(istat)
            if record is not None and record.logo_b64:
                contatori["con_logo"] += 1
        print(riga, file=sys.stderr)
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

    contatori = _esegui_registro(comuni, delay=args.delay)
    print(
        f"scansionati {len(comuni)} · con-record {contatori['ok']} · "
        f"con-logo {contatori['con_logo']} · vuoti {contatori['vuoto']} · "
        f"errori {contatori['errore']}",
        file=sys.stderr,
    )
    return 0


def _anagrafe_comuni() -> dict[str, dict]:
    """Anagrafe ISTAT indicizzata per codice — serve sia a costruire i dict
    comune per `censisci_molti`, sia come lookup provincia/regione/sito per
    `_registra`."""
    if not COMUNI_ISTAT_PATH.exists():
        raise SystemExit(
            f"comuni-istat.json assente ({COMUNI_ISTAT_PATH}): esegui 'make frame-nazionale'."
        )
    elenco = json.loads(COMUNI_ISTAT_PATH.read_text("utf-8"))
    return {r["codice_istat"]: r for r in elenco}


def _fase_censimento(comuni_istat: list[str], args: argparse.Namespace) -> tuple[int, int]:
    """Fase 1 di sweep: misura i comuni e scrive storico.db (riusa il motore
    di `treasureiq.ingest.censimento`, nessun re-scraping qui).

    Ritorna (misurati, saltati-per-resume).
    """
    from datetime import datetime, timezone

    from treasureiq.ingest.censimento import _gia_registrati, _registra, censisci_molti

    anagrafe = _anagrafe_comuni()
    oggi = datetime.now(timezone.utc).date()
    gia_fatti = _gia_registrati(args.db, oggi)
    da_misurare = [
        anagrafe[istat] for istat in comuni_istat if istat in anagrafe and istat not in gia_fatti
    ]
    saltati = len(comuni_istat) - len(da_misurare)
    if not da_misurare:
        return 0, saltati

    args.db.parent.mkdir(parents=True, exist_ok=True)
    try:
        censisci_molti(
            da_misurare,
            leggi_pagina=not args.tutti,
            lavoratori=args.lavoratori,
            misura_piattaforma=True,
            misura_aderenza=args.aderenza and not args.tutti,
            salva=lambda blocco: _registra(blocco, db=args.db, anagrafe=anagrafe),
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
    contatori = _esegui_registro(comuni_registro, delay=args.delay)

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.registro_cli",
        description="Popola/ispeziona il registro per-comune (data-live/registro/<istat>.json).",
    )
    sub = parser.add_subparsers(dest="comando")

    scan = sub.add_parser("scan", help="Scansiona comuni e scrive il registro (default).")
    _add_selezione_args(scan)
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
    sweep.add_argument("--db", type=Path, default=DATA_DIR / "storico.db",
                        help="Path a storico.db (default data/storico.db; con 'make sweep' "
                             "è /scrivibile/storico.db).")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"scan", "sweep", "list", "-h", "--help"}:
        argv = ["scan", *argv]
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.comando is None:
        args.comando = "scan"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
