"""Lettore uffici Agenda Smart dal payload server-rendered di ``/uffici``."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlsplit

from treasureiq.ingest.host_guard import fetch_guardato
from treasureiq.ingest.piattaforma import Piattaforma

MAX_BYTES = 6_000_000
_CONTENTS = re.compile(r'<explore-info\b[^>]*\s:contents="([^"]*)"', re.I | re.S)
_TOTAL = re.compile(r'\s:?total="(\d+)"', re.I)
_PAGE_SIZE = 6
# The component renders six cards per page. An index beyond this bound needs a
# dedicated reader; returning no partial result keeps the stored data honest.
MAX_UFFICI_INDICE = 200
MAX_PAGINE_UFFICI = math.ceil(MAX_UFFICI_INDICE / _PAGE_SIZE)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _contenuti_da_html(pagina: str) -> tuple[list[object], int] | None:
    match = _CONTENTS.search(pagina)
    if match is None:
        return None
    try:
        contenuti = json.loads(unescape(match.group(1)))
    except json.JSONDecodeError:
        return None
    if not isinstance(contenuti, list):
        return None
    fine_tag = pagina.find(">", match.end())
    totale_match = _TOTAL.search(pagina[match.start() : fine_tag + 1])
    totale = int(totale_match.group(1)) if totale_match else len(contenuti)
    return contenuti, totale


def _uffici_da_html(pagina: str, base: str, host_atteso: str, letto_il: str):
    from treasureiq.connettore import UfficioConnettore

    contenuti_totale = _contenuti_da_html(pagina)
    if contenuti_totale is None:
        return None
    contenuti, _ = contenuti_totale
    uffici = []
    visti: set[str] = set()
    for voce in contenuti:
        if not isinstance(voce, dict):
            continue
        nome = voce.get("title")
        share_url = voce.get("share_url")
        if not isinstance(nome, str) or not isinstance(share_url, str):
            continue
        nome = nome.strip()
        share_url = share_url.strip()
        if not nome or not share_url:
            continue
        url = urljoin(base, share_url)
        if _host(url) != host_atteso or url in visti:
            continue
        visti.add(url)
        uffici.append(UfficioConnettore(nome=nome, url=url, source_typed=False, letto_il=letto_il))
    return uffici


def leggi_agenda_smart(comune, sonda, *, fetch=fetch_guardato):
    """Legge ``/uffici`` senza seguire le schede individuali."""
    from treasureiq.connettore import EsitoConnettore
    from treasureiq.mappa_connettore import _base_con_schema

    letto_il = datetime.now(timezone.utc).isoformat()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(codice_istat=comune.codice_istat, piattaforma=Piattaforma.AGENDA_SMART.value, letto_il=letto_il)
    host = _host(base)
    url = urljoin(base.rstrip("/") + "/", "uffici")
    risposta = fetch(url, timeout=8.0, max_bytes=MAX_BYTES, host_atteso=host)
    if risposta is None:
        return EsitoConnettore(codice_istat=comune.codice_istat, piattaforma=Piattaforma.AGENDA_SMART.value, letto_il=letto_il)
    sonda.richieste += 1
    sonda.raggiungibile = True
    pagina, finale = risposta[1], risposta[2]
    testo = pagina.decode("utf-8", "replace")
    prima_pagina = _uffici_da_html(testo, finale, host, letto_il)
    contenuti_totale = _contenuti_da_html(testo)
    if prima_pagina is None or contenuti_totale is None:
        prima_pagina, totale = [], 0
    else:
        totale = contenuti_totale[1]
    uffici = prima_pagina
    if totale > MAX_UFFICI_INDICE:
        uffici = []
    else:
        for numero in range(2, min(math.ceil(totale / _PAGE_SIZE), MAX_PAGINE_UFFICI) + 1):
            successiva = fetch(f"{url}?page={numero}", timeout=8.0, max_bytes=MAX_BYTES, host_atteso=host)
            if successiva is None:
                uffici = []
                break
            sonda.richieste += 1
            pagina_uffici = _uffici_da_html(successiva[1].decode("utf-8", "replace"), successiva[2], host, letto_il)
            if pagina_uffici is None:
                uffici = []
                break
            uffici.extend(pagina_uffici)
    visti: set[str] = set()
    uffici = [ufficio for ufficio in uffici if not (ufficio.url in visti or visti.add(ufficio.url))]
    return EsitoConnettore(codice_istat=comune.codice_istat, piattaforma=Piattaforma.AGENDA_SMART.value, letto_il=letto_il, uffici=uffici[:MAX_UFFICI_INDICE])
