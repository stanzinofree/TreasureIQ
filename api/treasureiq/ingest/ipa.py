"""Read the Indice della Pubblica Amministrazione and record who to write to.

Usage:
    python -m treasureiq.ingest.ipa [--enti data/enti.json] [--dry-run]

IPA is the register every Italian public body is legally required to keep
current. It is published as open data through a CKAN API built for
programmatic access, which makes it the right instrument for "which office,
and how do I reach it" — the question a web search answers badly. A search
engine ranks; it does not certify. It will happily put a lookalike domain or a
commercial intermediary above the comune's own page, and the citizen reading
the answer is the one least equipped to notice. It also rate-limits, so the
answer depends on whether we happen to be in favour that day.

What IPA does not publish is opening hours: it records the institutional
channel, not the counter timetable. Those stay where they already are, in
`UrpContact`, read from the comune's own page and dated there. Each source is
cited for what it actually knows, and neither is asked to cover for the other.

The download happens here, at ingestion. Nothing in a citizen's request path
touches the network (D-28).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
from datetime import date
from pathlib import Path

from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

CKAN_PACKAGE = "https://indicepa.gov.it/ipa-dati/api/3/action/package_show?id=amministrazioni"

#: Only municipal records are of interest, and `des_amm` is how IPA spells
#: them out ("Comune di Albano Laziale").
_PREFISSO_COMUNE = "comune di "


def _risorsa_txt(client: httpx.Client) -> str:
    """The current download URL for the amministrazioni table.

    Resolved through the API rather than hardcoded: CKAN resource URLs carry
    generated UUIDs and change when the dataset is republished.
    """
    payload = client.get(CKAN_PACKAGE, timeout=30.0).raise_for_status().json()
    for risorsa in payload["result"]["resources"]:
        if (risorsa.get("format") or "").upper() == "TXT":
            return risorsa["url"]
    raise RuntimeError("IPA: nessuna risorsa TXT nel dataset amministrazioni")


def _scarica(client: httpx.Client, url: str) -> list[dict[str, str]]:
    testo = client.get(url, timeout=180.0, follow_redirects=True).raise_for_status().text
    # The file is served with a BOM, which otherwise ends up glued to the first
    # header ("﻿cod_amm") and makes that column unreachable by name.
    return list(csv.DictReader(io.StringIO(testo.lstrip("﻿")), delimiter="\t"))


def _pec(riga: dict[str, str]) -> str | None:
    """The first address IPA marks as certified.

    The table holds up to five addresses with a type beside each, and only the
    `pec` ones are the channel that legally obliges a reply. Taking `mail1`
    blindly would hand a citizen an ordinary inbox and call it official.
    """
    for i in range(1, 6):
        indirizzo = (riga.get(f"mail{i}") or "").strip()
        tipo = (riga.get(f"tipo_mail{i}") or "").strip().lower()
        if indirizzo and indirizzo.lower() != "null" and tipo == "pec":
            return indirizzo
    return None


def _pulisci(valore: str | None) -> str | None:
    if valore is None:
        return None
    valore = valore.strip()
    return None if not valore or valore.lower() == "null" else valore


def _host(url: str | None) -> str | None:
    """L'host di un sito, normalizzato per il confronto.

    Il registro scrive gli indirizzi in mille modi — con e senza schema, con e
    senza `www.`, con la barra finale — e confrontarli come stringhe perderebbe
    metà degli agganci.
    """
    grezzo = (url or "").strip()
    if not grezzo:
        return None
    if "//" not in grezzo:
        grezzo = f"https://{grezzo}"
    host = (urlsplit(grezzo).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def arricchisci_comuni(comuni: list[dict], righe: list[dict]) -> tuple[int, int]:
    """Scrive `codice_ipa` su ogni comune che si riesce ad agganciare.

    L'aggancio primario è l'host del sito istituzionale, perché il campo
    `sito` dei nostri comuni viene da questo stesso registro: è la chiave che
    li lega davvero. Il ripiego su nome e provincia serve ai comuni che hanno
    cambiato dominio da quando il file è stato costruito.

    Il codice viene salvato in **maiuscolo**: il registro lo distribuisce
    minuscolo (`c_a138`), e i portali MyPortal a quella forma rispondono `200`
    con zero contenuti invece che con un errore — cioè un comune che sembra
    non pubblicare niente.

    Chi non si aggancia resta senza il campo, non con una stringa vuota: a
    valle un codice assente e un codice vuoto si comportano diversamente, e
    solo il primo dice la verità.
    """
    per_host: dict[str, str] = {}
    per_nome: dict[tuple[str, str], str] = {}
    for riga in righe:
        codice = (riga.get("cod_amm") or "").strip().upper()
        if not codice:
            continue
        host = _host(riga.get("sito_istituzionale"))
        if host:
            per_host.setdefault(host, codice)
        chiave = (
            (riga.get("Comune") or "").strip().casefold(),
            (riga.get("Provincia") or "").strip().casefold(),
        )
        if chiave[0]:
            per_nome.setdefault(chiave, codice)

    agganciati = 0
    for comune in comuni:
        codice = per_host.get(_host(comune.get("sito")) or "")
        if codice is None:
            codice = per_nome.get(
                (comune.get("nome", "").strip().casefold(), comune.get("provincia", "").strip().casefold())
            )
        if codice:
            comune["codice_ipa"] = codice
            agganciati += 1
    return agganciati, len(comuni) - agganciati


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--enti", default="data/enti.json")
    p.add_argument(
        "--comuni",
        metavar="FILE",
        help=(
            "Invece degli enti, arricchisci l'elenco nazionale dei comuni con il "
            "codice IPA (serve a indirizzare le API dei portali MyPortal)."
        ),
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.comuni:
        percorso = Path(args.comuni)
        comuni = json.loads(percorso.read_text("utf-8"))
        with httpx.Client() as client:
            righe = _scarica(client, _risorsa_txt(client))
        logger.info("IPA: %d amministrazioni nel registro", len(righe))
        agganciati, mancanti = arricchisci_comuni(comuni, righe)
        logger.info("IPA: %d comuni agganciati, %d senza codice", agganciati, mancanti)
        if args.dry_run:
            return 0
        percorso.write_text(
            json.dumps(comuni, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        logger.info("scritto %s", percorso)
        return 0

    percorso = Path(args.enti)
    enti = json.loads(percorso.read_text("utf-8"))

    with httpx.Client() as client:
        url = _risorsa_txt(client)
        logger.info("IPA: scarico %s", url)
        righe = _scarica(client, url)
    logger.info("IPA: %d amministrazioni nel registro", len(righe))

    # Index by (comune, province) rather than by name alone. The register holds
    # "Comune di Albano Sant'Alessandro" in Bergamo alongside our Albano
    # Laziale, and "Marino" is both a comune in Roma and a common surname, so
    # a prefix match on the name would quietly attach the wrong body's PEC to
    # the wrong citizens. The province is what makes the match unambiguous.
    per_comune: dict[tuple[str, str], dict[str, str]] = {}
    for riga in righe:
        des = (riga.get("des_amm") or "").strip().lower()
        if not des.startswith(_PREFISSO_COMUNE):
            continue
        chiave = (
            (riga.get("Comune") or "").strip().casefold(),
            (riga.get("Provincia") or "").strip().casefold(),
        )
        per_comune.setdefault(chiave, riga)

    oggi = date.today()
    aggiornati = mancanti = 0
    for ente in enti:
        nome = ente["ente"].removeprefix("Comune di ").strip()
        riga = per_comune.get((nome.casefold(), "rm"))
        if riga is None:
            logger.warning("IPA: nessuna corrispondenza per %s", ente["ente"])
            mancanti += 1
            continue
        ente["ipa"] = {
            "codice_ipa": riga["cod_amm"],
            "denominazione": riga["des_amm"],
            "pec": _pec(riga),
            "indirizzo": _pulisci(riga.get("Indirizzo")),
            "sito": _pulisci(riga.get("sito_istituzionale")),
            "fonte": "https://indicepa.gov.it/ipa-dati/dataset/amministrazioni",
            "verificato_il": oggi.isoformat(),
        }
        aggiornati += 1
        logger.info(
            "IPA: %-22s cod=%-8s pec=%s",
            nome,
            riga["cod_amm"],
            ente["ipa"]["pec"] or "—",
        )

    if args.dry_run:
        logger.info("dry-run: nessuna scrittura (%d aggiornati, %d mancanti)", aggiornati, mancanti)
        return 0

    percorso.write_text(json.dumps(enti, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    logger.info("scritto %s — %d aggiornati, %d mancanti", percorso, aggiornati, mancanti)
    return 0


if __name__ == "__main__":
    sys.exit(main())
