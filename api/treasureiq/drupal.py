"""Connettore uffici per Drupal Bootstrap Italia server-rendered."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from treasureiq.connettore import EsitoConnettore, UfficioConnettore
from treasureiq.ingest.base import USER_AGENT
from treasureiq.ingest.censimento import _Sonda
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import ComuneNoto

logger = logging.getLogger(__name__)

PIATTAFORMA_DRUPAL = "drupal"
MAX_RISPOSTA_BYTES = 2_000_000
MAX_PAGINE_UFFICI = 20
MAX_UFFICI_INDICE = 200

_RE_ANCORA = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_RE_HREF = re.compile(r'''\bhref=["']([^"']+)["']''', re.IGNORECASE)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_H3 = re.compile(r"<h3\b([^>]*)>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
_RE_CARD_TITLE = re.compile(r"\bcard-title\b", re.IGNORECASE)
_RE_SERVICE_AREA = re.compile(r'''\bdata-element=["']service-area["']''', re.IGNORECASE)
_RE_PAGINA = re.compile(r"(?:[?&]|&amp;)page=(\d+)", re.IGNORECASE)


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stesso_host(url: str, host_comune: str) -> bool:
    return _host_senza_www(urlparse(url).netloc.lower()) == host_comune


def _richiedi_con_guardia(url: str, host_comune: str, *, timeout: float) -> tuple[str, str] | None:
    if urlparse(url).scheme not in ("http", "https"):
        return None
    try:
        with httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            with client.stream("GET", url) as risposta:
                if risposta.status_code != 200 or not _stesso_host(str(risposta.url), host_comune):
                    return None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_RISPOSTA_BYTES:
                        return None
                return bytes(buffer).decode("utf-8", errors="replace"), str(risposta.url)
    except Exception:  # noqa: BLE001 — indice Drupal muto: esito vuoto, mai crash
        logger.info("drupal: indice irraggiungibile: %s", url)
        return None


def _fetch(url: str, host_comune: str, timeout: float, sonda: _Sonda) -> tuple[str, str] | None:
    esito = _richiedi_con_guardia(url, host_comune, timeout=timeout)
    if esito is not None:
        sonda.richieste += 1
        sonda.raggiungibile = True
    return esito


def _ancore(pagina: str, base: str, host_comune: str) -> list[tuple[str, str, str]]:
    trovate: list[tuple[str, str, str]] = []
    for attributi, corpo in _RE_ANCORA.findall(pagina):
        match_href = _RE_HREF.search(attributi)
        if match_href is None:
            continue
        href = html.unescape(match_href.group(1)).strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        url = urljoin(base, href)
        if not _stesso_host(url, host_comune):
            continue
        testo = re.sub(r"\s+", " ", html.unescape(_RE_TAG.sub(" ", corpo))).strip()
        trovate.append((url, testo, attributi))
    return trovate


def _e_scheda_ufficio(url: str, attributi: str) -> bool:
    segmenti = [parte for parte in urlparse(url).path.lower().split("/") if parte]
    return (
        len(segmenti) == 3 and segmenti[:2] == ["amministrazione", "uffici"]
    ) or (
        len(segmenti) == 2
        and segmenti[0] == "amministrazione"
        and _RE_SERVICE_AREA.search(attributi) is not None
    )


def _uffici_da_pagina(pagina: str, base: str, host_comune: str, letto_il: str) -> list[UfficioConnettore]:
    uffici: list[UfficioConnettore] = []
    visti: set[str] = set()
    for attributi, titolo in _RE_H3.findall(pagina):
        if not _RE_CARD_TITLE.search(attributi):
            continue
        for url, nome, attributi_ancora in _ancore(titolo, base, host_comune):
            if not _e_scheda_ufficio(url, attributi_ancora) or url in visti or not nome:
                continue
            visti.add(url)
            uffici.append(UfficioConnettore(nome=nome, url=url, source_typed=False, letto_il=letto_il))
    return uffici


def leggi_drupal(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Legge le card uffici Drupal BI, inclusa la paginazione server-rendered."""
    letto_il = _ora()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_DRUPAL, letto_il=letto_il)
    host_comune = _host_senza_www(urlparse(base).netloc.lower())
    indice = urljoin(base, "/amministrazione/uffici")
    uffici: list[UfficioConnettore] = []
    visti: set[str] = set()
    pagina_numero = 0
    ultima_pagina = 0

    while pagina_numero <= min(ultima_pagina, MAX_PAGINE_UFFICI - 1):
        url = indice if pagina_numero == 0 else f"{indice}?page={pagina_numero}"
        letto = _fetch(url, host_comune, 8.0, sonda)
        if letto is None:
            break
        pagina, url_finale = letto
        for ufficio in _uffici_da_pagina(pagina, url_finale, host_comune, letto_il):
            if ufficio.url in visti:
                continue
            visti.add(ufficio.url)
            uffici.append(ufficio)
            if len(uffici) >= MAX_UFFICI_INDICE:
                return EsitoConnettore(
                    codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_DRUPAL,
                    letto_il=letto_il, uffici=uffici,
                )
        numeri = [int(numero) for numero in _RE_PAGINA.findall(pagina)]
        if numeri:
            ultima_pagina = max(ultima_pagina, max(numeri))
        pagina_numero += 1

    return EsitoConnettore(
        codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_DRUPAL,
        letto_il=letto_il, uffici=uffici,
    )
