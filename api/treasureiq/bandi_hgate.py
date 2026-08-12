"""Query live dei bandi di gara su portali Halley EGov (hgate).

PoC di navigazione live: dato un comune il cui portale di Amministrazione
Trasparente è classificato `hgate` nel censimento (`storico.db`), risale la
catena reale del portale — landing trasparenza → ancora "Bandi di gara e
contratti" → sezione legacy `.HBL` (EGSCHTST26) — e restituisce l'elenco dei
bandi pubblicati (titolo, data, CIG se leggibile in elenco, link scheda).

Confini onesti:
- si ferma all'ELENCO. Non apre le schede, non scarica né analizza PDF.
- il CIG in elenco è spesso parziale o assente (vive nella scheda di
  dettaglio): il campo resta `None` quando non è leggibile, mai indovinato.
- ogni fetch passa dalla guardia SSRF per-hop `fetch_guardato`, ancorata al
  dominio del portale AT del comune. Nessuna URL fuori host viene seguita.

CLI:
    python -m treasureiq.bandi_hgate <codice_istat> [--timeout SEC]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from treasureiq.ingest.host_guard import fetch_guardato
from treasureiq.storico import portale_del_comune

STORICO_DB = Path(__file__).resolve().parent.parent.parent / "data" / "storico.db"

# fetch legacy .HBL è lento (CGI): cap generoso di default.
TIMEOUT_DEFAULT = 50.0
MAX_BYTES = 4_000_000

_ANCORA = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_ETICHETTA_BANDI = re.compile(r"bandi\s+di\s+gara", re.I)
# Ogni riga bando è un'ancora al dettaglio, seguita — quando presente — da un
# `<p class="small"><strong>CIG:</strong> XXXX</p>` che è la fonte AUTOREVOLE
# del CIG (l'elenco linka anche la dashboard ANAC su quel codice).
_RIGA_BANDO = re.compile(
    r'<a class="fw-semibold"\s+href="([^"]*scheda_bando[^"]*)">(.*?)</a>'
    r'(?:\s*<p[^>]*>\s*<strong>\s*CIG\s*:?\s*</strong>\s*([0-9A-Z]{10}))?',
    re.I | re.S,
)
_TAG = re.compile(r"<[^>]+>")
_SPAZI = re.compile(r"\s+")
_DATA = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")
# CIG dal titolo: token 10 alfanumerici maiuscoli vicino alla parola CIG.
_CIG = re.compile(r"\bCIG\b[\s:]*([0-9A-Z]{10})\b")


def _testo(html: str) -> str:
    """HTML inline → testo piatto, spazi normalizzati."""
    return _SPAZI.sub(" ", _TAG.sub(" ", html)).strip()


@dataclass
class BandoHgate:
    titolo: str
    url_scheda: str
    data: str | None = None
    cig: str | None = None


@dataclass
class EsitoBandiHgate:
    esito: str  # ok | comune_ignoto | non_hgate | at_url_assente |
    #             sezione_non_trovata | portale_non_raggiungibile
    codice_istat: str
    comune: str | None = None
    at_url: str | None = None
    gara_url: str | None = None
    bandi: list[BandoHgate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _estrai_gara_url(landing_html: str, at_url: str) -> str | None:
    """Trova l'ancora 'Bandi di gara e contratti' nella landing trasparenza."""
    for href, etichetta in _ANCORA.findall(landing_html):
        if _ETICHETTA_BANDI.search(_testo(etichetta)):
            return href
    return None


def _parse_bandi(listato_html: str) -> list[BandoHgate]:
    """Estrae le righe scheda_bando dall'elenco EGSCHTST26."""
    bandi: list[BandoHgate] = []
    for url_scheda, titolo_html, cig_p in _RIGA_BANDO.findall(listato_html):
        titolo = _testo(titolo_html)
        if not titolo:
            continue
        data = None
        m_data = _DATA.search(titolo)
        if m_data:
            data = "-".join(m_data.groups())
        # CIG autorevole dal <p> sibling; fallback al codice nel titolo.
        cig = cig_p or None
        if not cig:
            m_cig = _CIG.search(titolo)
            if m_cig:
                cig = m_cig.group(1)
        bandi.append(BandoHgate(titolo=titolo, url_scheda=url_scheda, data=data, cig=cig))
    return bandi


def bandi_hgate(codice_istat: str, *, timeout: float = TIMEOUT_DEFAULT) -> EsitoBandiHgate:
    """Elenca i bandi live per un comune hgate. Non solleva: l'esito è nel campo."""
    riga = portale_del_comune(STORICO_DB, codice_istat)
    if not riga:
        return EsitoBandiHgate(esito="comune_ignoto", codice_istat=codice_istat)

    comune = riga.get("nome")
    if riga.get("piattaforma_at") != "hgate":
        return EsitoBandiHgate(
            esito="non_hgate", codice_istat=codice_istat, comune=comune,
        )

    at_url = riga.get("at_url")
    if not at_url:
        return EsitoBandiHgate(
            esito="at_url_assente", codice_istat=codice_istat, comune=comune,
        )

    host = urlsplit(at_url).hostname
    host_atteso = host.lower().removeprefix("www.") if host else None

    landing = fetch_guardato(
        at_url, timeout=timeout, max_bytes=MAX_BYTES, host_atteso=host_atteso,
    )
    if not landing:
        return EsitoBandiHgate(
            esito="portale_non_raggiungibile", codice_istat=codice_istat,
            comune=comune, at_url=at_url,
        )

    gara_url = _estrai_gara_url(landing[1].decode("utf-8", "replace"), at_url)
    if not gara_url:
        return EsitoBandiHgate(
            esito="sezione_non_trovata", codice_istat=codice_istat,
            comune=comune, at_url=at_url,
        )

    listato = fetch_guardato(
        gara_url, timeout=timeout, max_bytes=MAX_BYTES, host_atteso=host_atteso,
    )
    if not listato:
        return EsitoBandiHgate(
            esito="portale_non_raggiungibile", codice_istat=codice_istat,
            comune=comune, at_url=at_url, gara_url=gara_url,
        )

    bandi = _parse_bandi(listato[1].decode("utf-8", "replace"))
    return EsitoBandiHgate(
        esito="ok", codice_istat=codice_istat, comune=comune,
        at_url=at_url, gara_url=gara_url, bandi=bandi,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="treasureiq.bandi_hgate",
        description="Elenca i bandi di gara live di un comune su portale Halley EGov (hgate).",
    )
    parser.add_argument("codice_istat", help="Codice ISTAT del comune (es. 109012)")
    parser.add_argument(
        "--timeout", type=float, default=TIMEOUT_DEFAULT,
        help=f"Timeout per fetch, secondi (default {TIMEOUT_DEFAULT})",
    )
    args = parser.parse_args(argv)

    esito = bandi_hgate(args.codice_istat, timeout=args.timeout)
    print(json.dumps(esito.to_dict(), ensure_ascii=False, indent=2))
    return 0 if esito.esito == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
