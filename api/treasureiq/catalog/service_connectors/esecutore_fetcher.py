"""``ServiceFetcher`` guardato dalla ``PoliticaFetch`` (Ramo 3, Slice 5).

Il ``HttpxServiceFetcher`` di Slice 4 apre ``httpx`` diretto: ottimo per i test
unitari del confine HTTP, ma una cache-miss dalla chat bypasserebbe rate-limit
per dominio, budget, backoff e timeout centralizzati. Il **runtime** usa invece
questo adapter, che instrada ogni fetch attraverso l'``EsecutoreFetch``
condiviso di processo (§1.1/§1.2 del design).

Contratto (D-S5-6):
- host ufficiale passato come ``host_atteso`` a ogni chiamata → la validazione
  host su URL iniziale e su OGNI hop, più il check SSRF sull'IP, è già di
  ``fetch_guardato``: l'adapter **non** duplica alcun controllo host/redirect;
- ``max_bytes`` distinti — piccolo per il JSON REST, ampio per l'HTML;
- ``consentito=False`` (rate-limit/budget) → **miss** (``()``/``None``), senza
  retry autonomo: il retry/backoff è della politica, non dell'adapter;
- ``fetched is None`` o payload non decodificabile / JSON malformato → miss;
- params REST bakeati nell'URL (come Slice 4).
"""

from __future__ import annotations

import json
from urllib.parse import urlencode, urlparse

from treasureiq.catalog.fetch_runtime import EsecutoreFetch
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.ingest.host_guard import host_senza_www

#: Timeout esplicito per le query live dei servizi (dal coordinatore).
_TIMEOUT_S = 10.0

#: La ricerca REST torna un JSON piccolo (id/title/link, ``per_page`` basso);
#: la pagina servizio è HTML e va lasciata più ampia. Cap distinti così una
#: ricerca non paga il budget di byte di una pagina e viceversa.
_MAX_BYTES_REST = 512 * 1024
_MAX_BYTES_HTML = 4 * 1024 * 1024


def _bytes_di(esito) -> bytes | None:
    """I bytes del corpo da un ``EsitoFetch``, o ``None`` per un miss.

    ``fetched`` è ``(headers, bytes, url_finale)`` (3-tupla) su successo,
    ``None`` su risorsa muta. ``consentito=False`` è un rifiuto della politica
    (budget/rate-limit): niente rete interrogata, quindi miss senza retry.
    """
    if not esito.consentito or esito.fetched is None:
        return None
    # La 2ª posizione è il corpo in bytes (vedi fetch_guardato); difensivo su
    # forme inattese della tupla.
    if len(esito.fetched) < 2:
        return None
    corpo = esito.fetched[1]
    return corpo if isinstance(corpo, (bytes, bytearray)) else None


class EsecutoreServiceFetcher:
    """``ServiceFetcher`` che passa da un ``EsecutoreFetch`` guardato.

    Stesso Protocol del ``HttpxServiceFetcher``, ma il fetch reale è mediato
    dalla ``PoliticaFetch`` (budget/rate-limit/backoff) via ``fetch_guardato``.
    Nessun login, nessun cookie.
    """

    def __init__(self, esecutore: EsecutoreFetch) -> None:
        self._esecutore = esecutore

    def cerca_servizi(
        self,
        *,
        base_url: str,
        rest_base: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        # URL identico a Slice 4, con i params bakeati: search + per_page + i soli
        # campi che servono. Un solo GET deterministico, nessun fan-out.
        params = urlencode({"search": term, "per_page": limit, "_fields": "id,title,link"})
        url = f"{base_url.rstrip('/')}/wp-json/wp/v2/{rest_base}?{params}"
        host_atteso = host_senza_www(urlparse(base_url).netloc.lower())

        esito = self._esecutore.esegui(
            url, timeout=_TIMEOUT_S, max_bytes=_MAX_BYTES_REST, host_atteso=host_atteso
        )
        corpo = _bytes_di(esito)
        if corpo is None:
            return ()
        try:
            dati = json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return ()
        if not isinstance(dati, list):
            return ()
        candidati: list[ServiceCandidate] = []
        for voce in dati:
            candidato = self._candidato(voce)
            if candidato is not None:
                candidati.append(candidato)
        return tuple(candidati)

    @staticmethod
    def _candidato(voce: object) -> ServiceCandidate | None:
        # Speculare a HttpxServiceFetcher._candidato: id stabile, titolo dal
        # `rendered`, url dal `link`; qualunque campo assente/errato → scarto.
        if not isinstance(voce, dict):
            return None
        titolo_raw = voce.get("title")
        titolo = titolo_raw.get("rendered") if isinstance(titolo_raw, dict) else titolo_raw
        try:
            return ServiceCandidate(
                wordpress_id=int(voce["id"]),
                title=str(titolo).strip(),
                url=str(voce["link"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        host_atteso = host_senza_www(official_host.lower())
        esito = self._esecutore.esegui(
            url, timeout=_TIMEOUT_S, max_bytes=_MAX_BYTES_HTML, host_atteso=host_atteso
        )
        corpo = _bytes_di(esito)
        if corpo is None:
            return None
        try:
            return corpo.decode("utf-8")
        except UnicodeDecodeError:
            return None
