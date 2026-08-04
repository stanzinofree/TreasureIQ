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
from pathlib import Path

import httpx

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


def main(argv: list[str] | None = None) -> int:
    """CLI: costruisce data/comuni-istat.json da ISTAT e IPA."""
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.ingest.comuni_istat",
        description=(
            "Unisce l'elenco ISTAT dei comuni con i siti istituzionali di IPA "
            "e scrive il frame nazionale usato da censimento e sonda live."
        ),
    )
    parser.add_argument("--out", type=Path, required=True, help="File JSON da scrivere.")
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

    args.out.write_text(json.dumps(comuni, ensure_ascii=False, indent=1) + "\n", "utf-8")

    totale = len(comuni)
    copertura = conteggi["abbinati"] / totale
    print(f"comuni ISTAT            : {totale}")
    print(f"con sito da IPA         : {conteggi['abbinati']} ({copertura:.1%})")
    print(f"  di cui su solo nome   : {conteggi['recuperati_su_nome']}")
    print(f"scartati per ambiguità  : {conteggi['ambigui']}")
    print(f"senza sito              : {totale - conteggi['abbinati'] - conteggi['ambigui']}")
    print(f"scritto in {args.out}")

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


if __name__ == "__main__":
    raise SystemExit(main())
