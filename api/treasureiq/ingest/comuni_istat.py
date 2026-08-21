"""Il frame nazionale: quali comuni esistono, e dove stanno online.

Nessuno dei due elenchi pubblici basta da solo. ISTAT dice quali comuni
esistono e con che codice, ma non dove sono online. IPA dice dove sono online,
ma non porta il codice ISTAT. Questo modulo li unisce e produce
`data/comuni-istat.json`, che è ciò che permette a `sonda_live` di riconoscere
un comune qualunque e a `censimento` di campionare l'Italia invece dei cinque
comuni che abbiamo già letto.

Il join è per nome + sigla di provincia, normalizzati, con due filtri che
esistono entrambi per non fabbricare dati:

1. **solo enti la cui denominazione è "Comune di …"**. IPA registra sotto
   `Comune: Arce` anche la Comunità Montana che ha lì la propria sede: senza
   questo filtro Arce si vedrebbe assegnare il sito di un altro ente. Un dato
   falso prodotto da noi è peggio di un buco.
2. **solo abbinamenti univoci**. Se due enti-comune rivendicano lo stesso
   comune ISTAT non vince nessuno: il sito resta `None` e il caso si conta.

Serve poi un secondo passaggio sul solo nome, per una ragione storica precisa:
IPA registra ancora le province sarde abolite nel 2016 (OT, OG, VS, CI) mentre
ISTAT usa quelle attuali, e 155 comuni veri cadevano soltanto sulla sigla. Quel
passaggio è ammesso solo dove il nome è univoco in tutta Italia — senza
provincia, "Castro" e "San Teodoro" sono due comuni diversi, e indovinare
darebbe a un comune il sito di un altro.

Un comune senza sito resta nel file con `sito: null`. Non conoscere il sito è
un fatto sul nostro censimento, non un comune che smette di esistere (D-35).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

from treasureiq import frame_manifest
from treasureiq.frame_validation import FrameOutcome, FrameValidator
from treasureiq.ingest.base import USER_AGENT

logger = logging.getLogger(__name__)

#: Verificati il 4 agosto 2026. Se uno dei due smette di rispondere, il
#: modulo lo dice e si ferma: non esiste un mirror di cui fidarsi in silenzio.
URL_ISTAT = "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv"
URL_IPA = (
    "https://indicepa.gov.it/ipa-dati/dataset/502ff370-1b2c-4310-94c7-f39ceb7500e3/"
    "resource/3ed63523-ff9c-41f6-a6fe-980f3d9e501f/download/amministrazioni.txt"
)

COL_CODICE = "Codice Comune formato alfanumerico"
COL_NOME = "Denominazione in italiano"
COL_SIGLA = "Sigla automobilistica"
COL_REGIONE = "Denominazione Regione"

E_UN_COMUNE = re.compile(r"^comune\s+di\s+", re.IGNORECASE)

#: Sotto questa copertura qualcosa si è rotto a monte — un cambio di schema,
#: una colonna rinominata — e va guardato, non accettato come fisiologico.
COPERTURA_ATTESA = 0.98


def norm(testo: str) -> str:
    """Chiave di confronto: senza accenti, senza punteggiatura, minuscola.

    "Agliè" e "Aglie'", "Sant'Angelo" e "Sant Angelo" devono cadere sulla
    stessa chiave, altrimenti il join perde comuni veri e li conta fra i non
    censiti — cioè trasforma un nostro difetto in un dato sull'Italia.
    """
    piatto = unicodedata.normalize("NFKD", testo)
    piatto = "".join(c for c in piatto if not unicodedata.combining(c))
    piatto = re.sub(r"[^\w\s]", " ", piatto.lower())
    return re.sub(r"\s+", " ", piatto).strip()


def _scarica(url: str, destinazione: Path) -> None:
    logger.info("scarico %s", url)
    with httpx.Client(
        timeout=120.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        destinazione.write_bytes(resp.content)


def leggi_istat(percorso: Path) -> list[dict]:
    """I comuni italiani, dal CSV ISTAT (latin-1, separato da `;`)."""
    righe = csv.DictReader(io.StringIO(percorso.read_text("latin-1")), delimiter=";")
    comuni = []
    for r in righe:
        codice = (r.get(COL_CODICE) or "").strip()
        nome = (r.get(COL_NOME) or "").strip()
        if not codice or not nome:
            continue
        comuni.append(
            {
                "codice_istat": codice,
                "nome": nome,
                "provincia": (r.get(COL_SIGLA) or "").strip(),
                "regione": (r.get(COL_REGIONE) or "").strip(),
                "sito": None,
            }
        )
    if not comuni:
        raise RuntimeError(
            f"nessun comune letto da {percorso}: le colonne attese "
            f"({COL_CODICE!r}, {COL_NOME!r}) non ci sono più"
        )
    return comuni


def leggi_ipa(percorso: Path) -> dict[tuple[str, str], set[str]]:
    """Siti per (nome comune, sigla provincia), solo da enti che sono comuni."""
    righe = csv.DictReader(
        io.StringIO(percorso.read_text("utf-8-sig")), delimiter="\t"
    )
    per_chiave: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in righe:
        if not E_UN_COMUNE.match((r.get("des_amm") or "").strip()):
            continue
        sito = (r.get("sito_istituzionale") or "").strip()
        if not sito:
            continue
        chiave = (norm(r.get("Comune") or ""), (r.get("Provincia") or "").strip().upper())
        if chiave[0] and chiave[1]:
            per_chiave[chiave].add(sito)
    return per_chiave


def _conta_nomi(comuni: list[dict]) -> dict[str, int]:
    """Quante volte ogni nome normalizzato ricorre fra i comuni italiani."""
    conteggio: dict[str, int] = defaultdict(int)
    for c in comuni:
        conteggio[norm(c["nome"])] += 1
    return conteggio


def unisci(comuni: list[dict], siti: dict[tuple[str, str], set[str]]) -> dict[str, int]:
    """Assegna a ogni comune il proprio sito. Modifica `comuni` sul posto."""
    conteggi = {"abbinati": 0, "ambigui": 0, "recuperati_su_nome": 0}

    for c in comuni:
        candidati = siti.get((norm(c["nome"]), c["provincia"].upper()), set())
        if len(candidati) == 1:
            c["sito"] = next(iter(candidati))
            conteggi["abbinati"] += 1
        elif len(candidati) > 1:
            conteggi["ambigui"] += 1

    # Secondo passaggio: le province storiche di IPA (vedi docstring).
    per_nome: dict[str, set[str]] = defaultdict(set)
    for (nome, _prov), lista in siti.items():
        per_nome[nome].update(lista)
    omonimi = {n for n, quanti in _conta_nomi(comuni).items() if quanti > 1}

    for c in comuni:
        if c["sito"]:
            continue
        nome = norm(c["nome"])
        if nome in omonimi:
            continue
        candidati = per_nome.get(nome, set())
        if len(candidati) == 1:
            c["sito"] = next(iter(candidati))
            conteggi["recuperati_su_nome"] += 1

    conteggi["abbinati"] += conteggi["recuperati_su_nome"]
    return conteggi


def _now_iso() -> str:
    """Istante di generazione, UTC, in ISO-8601 (per il manifest)."""
    return datetime.now(timezone.utc).isoformat()


def diff_upstream(frame_path: Path, istat_csv: Path) -> dict:
    """Confronta il frame corrente con l'elenco ISTAT fresco. Solo lettura.

    Torna gli scarti sull'insieme dei ``codice_istat``: comuni nuovi a monte,
    comuni spariti dal frame (candidate soppressioni/fusioni) e comuni con lo
    stesso codice ma nome diverso (rinomine). NON riscrive nulla: la decisione,
    e a maggior ragione la migrazione fisica degli artefatti keyed sul codice,
    è una fase coordinata separata (lock storage-lifecycle).
    """
    from treasureiq.municipality_registry import get_registry

    upstream = {c["codice_istat"]: c["nome"] for c in leggi_istat(istat_csv)}
    reg = get_registry(frame_path)
    current = {r.codice_istat: r.nome for r in reg.frame.tutti()}

    aggiunti = sorted(set(upstream) - set(current))
    rimossi = sorted(set(current) - set(upstream))
    rinominati = sorted(
        cod
        for cod in set(current) & set(upstream)
        if norm(current[cod]) != norm(upstream[cod])
    )
    return {
        "aggiunti": [{"codice": c, "nome": upstream[c]} for c in aggiunti],
        "rimossi": [{"codice": c, "nome": current[c]} for c in rimossi],
        "rinominati": [
            {"codice": c, "prima": current[c], "dopo": upstream[c]} for c in rinominati
        ],
    }


def pianifica_transizioni(diff: dict) -> list[dict]:
    """Traduce il diff in transizioni amministrative da rivedere (non applicate).

    Ogni voce è un cambiamento che tocca gli artefatti keyed sul codice ISTAT
    (seed ``data/seed/{ente}_{codice}``, righe in ``storico.db``, snapshot del
    catalogo). Applicarle — spostare o riscrivere quegli artefatti — è bloccato
    finché storage-lifecycle non chiude il contratto dei root e il rollback:
    qui si producono solo il piano e la sua motivazione.
    """
    piano: list[dict] = []
    for voce in diff["rimossi"]:
        piano.append(
            {
                "tipo": "SOPPRESSIONE_O_FUSIONE",
                "codice": voce["codice"],
                "nome": voce["nome"],
                "azione": "rivedere: codice sparito a monte; verificare fusione "
                "verso un nuovo codice prima di orfanare gli artefatti.",
            }
        )
    for voce in diff["rinominati"]:
        piano.append(
            {
                "tipo": "RINOMINA",
                "codice": voce["codice"],
                "azione": f"solo etichetta: «{voce['prima']}» → «{voce['dopo']}», "
                "il codice resta; nessun artefatto da spostare.",
            }
        )
    for voce in diff["aggiunti"]:
        piano.append(
            {
                "tipo": "NUOVO",
                "codice": voce["codice"],
                "azione": f"nuovo comune «{voce['nome']}»: censibile, nessuna migrazione.",
            }
        )
    return piano


def _costruisci_frame(args: argparse.Namespace) -> tuple[list[dict], dict]:
    """Scarica (o riusa) le sorgenti e ricostruisce le righe del frame."""
    args.cartella_sorgenti.mkdir(parents=True, exist_ok=True)
    istat = args.cartella_sorgenti / "istat_comuni.csv"
    ipa = args.cartella_sorgenti / "ipa_amministrazioni.txt"

    for percorso, url in ((istat, URL_ISTAT), (ipa, URL_IPA)):
        if args.riusa_sorgenti and percorso.exists():
            print(f"riuso {percorso}", file=sys.stderr)
            continue
        _scarica(url, percorso)

    comuni = leggi_istat(istat)
    conteggi = unisci(comuni, leggi_ipa(ipa))
    return comuni, conteggi


def _pubblica(comuni: list[dict], conteggi: dict, out: Path) -> int:
    """Valida, poi scrive frame+manifest atomicamente. Rifiuta un frame INVALID.

    Il validatore gira *prima* della scrittura: un frame corrotto come sorgente
    di chiavi di join non deve mai sostituire quello buono. Se passa, si scrive
    in modo atomico (temp + rename) e si fissa il manifest di provenienza.
    """
    report = FrameValidator().validate(comuni)
    if report.outcome is FrameOutcome.INVALID:
        codici = ", ".join(sorted({i.code for i in report.blocking})) or "?"
        print(
            f"RIFIUTO la scrittura: il frame costruito è INVALID ({codici}). "
            f"Il frame esistente in {out} resta intatto.",
            file=sys.stderr,
        )
        for issue in report.blocking[:10]:
            print(f"  - {issue.detail}", file=sys.stderr)
        return 2

    totale = len(comuni)
    copertura = conteggi["abbinati"] / totale
    testo = json.dumps(comuni, ensure_ascii=False, indent=1) + "\n"
    frame_manifest.write_atomic(out, testo)

    manifest = frame_manifest.FrameManifest(
        sha256=frame_manifest.sha256_of(testo),
        row_count=totale,
        valid_codes=report.valid_codes,
        generated_at=_now_iso(),
        sources=(URL_ISTAT, URL_IPA),
        coverage=round(copertura, 6),
    )
    manifest_path = frame_manifest.write_manifest(out, manifest)

    print(f"comuni ISTAT            : {totale}")
    print(f"con sito da IPA         : {conteggi['abbinati']} ({copertura:.1%})")
    print(f"  di cui su solo nome   : {conteggi['recuperati_su_nome']}")
    print(f"scartati per ambiguità  : {conteggi['ambigui']}")
    print(f"senza sito              : {totale - conteggi['abbinati'] - conteggi['ambigui']}")
    print(f"scritto in {out}")
    print(f"manifest in {manifest_path} (sha256 {manifest.sha256[:12]}…)")

    if copertura < COPERTURA_ATTESA:
        # Un calo di copertura non è un arrotondamento: è una colonna
        # rinominata o uno schema cambiato a monte, e va guardato ora.
        print(
            f"\nATTENZIONE: copertura {copertura:.1%}, sotto l'attesa "
            f"{COPERTURA_ATTESA:.0%}. Controlla se ISTAT o IPA hanno cambiato schema.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI: costruisce/verifica/confronta data/comuni-istat.json."""
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.ingest.comuni_istat",
        description=(
            "Unisce l'elenco ISTAT dei comuni con i siti istituzionali di IPA "
            "e scrive il frame nazionale usato da censimento e sonda live."
        ),
    )
    parser.add_argument("--out", type=Path, help="File JSON da scrivere (modo build).")
    parser.add_argument(
        "--verifica",
        type=Path,
        metavar="FRAME",
        help="Verifica l'integrità di un frame contro il suo manifest ed esce.",
    )
    parser.add_argument(
        "--diff",
        type=Path,
        metavar="FRAME",
        help="Confronta un frame con l'elenco ISTAT fresco ed esce (solo report).",
    )
    parser.add_argument(
        "--cartella-sorgenti",
        type=Path,
        default=Path("/tmp"),
        help="Dove tenere i due file scaricati (default: /tmp).",
    )
    parser.add_argument(
        "--riusa-sorgenti",
        action="store_true",
        help="Non riscaricare se i file sono già lì. Utile offline e nei test.",
    )
    args = parser.parse_args(argv)

    # Modo verifica: duro, per build/CI. Frame ≠ manifest → uscita non-zero.
    if args.verifica is not None:
        ok, motivo = frame_manifest.verify(args.verifica)
        print(motivo, file=sys.stderr if not ok else sys.stdout)
        return 0 if ok else 1

    # Modo diff: report delle transizioni a monte, senza mai riscrivere.
    if args.diff is not None:
        istat = args.cartella_sorgenti / "istat_comuni.csv"
        if not (args.riusa_sorgenti and istat.exists()):
            args.cartella_sorgenti.mkdir(parents=True, exist_ok=True)
            _scarica(URL_ISTAT, istat)
        diff = diff_upstream(args.diff, istat)
        print(f"aggiunti a monte  : {len(diff['aggiunti'])}")
        print(f"rimossi dal frame : {len(diff['rimossi'])}")
        print(f"rinominati        : {len(diff['rinominati'])}")
        for t in pianifica_transizioni(diff):
            print(f"  [{t['tipo']}] {t['codice']}: {t['azione']}")
        return 0

    if args.out is None:
        parser.error("serve --out (build), --verifica FRAME o --diff FRAME")

    comuni, conteggi = _costruisci_frame(args)
    return _pubblica(comuni, conteggi, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
