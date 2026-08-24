"""``ServiceFetcher`` guardato dalla ``PoliticaFetch`` (Ramo 3, Slice 5).

Il ``HttpxServiceFetcher`` di Slice 4 apre ``httpx`` diretto: ottimo per i test
unitari del confine HTTP, ma una cache-miss dalla chat bypasserebbe rate-limit
per dominio, budget, backoff e timeout centralizzati. Il **runtime** usa invece
questo adapter, che instrada ogni fetch attraverso l'``EsecutoreFetch``
condiviso di processo (§1.1/§1.2 del design).

Struttura (Connettore #2): ``EsecutoreServiceFetcher`` è il **transport comune**
— apre i due primitivi di rete guardati (``scarica_json`` per il JSON REST,
``leggi_pagina`` per l'HTML) e nient'altro. La logica di **discovery** vive in una
**strategia** per famiglia (``_WpDiscovery`` qui, ``_ComWebDiscovery`` nel modulo
ComWeb): così WP e ComWeb condividono rete, host guard e rate-limit ma non la
scoperta. ``transport.con(strategia)`` compone il ``ServiceFetcher`` finale.

Contratto (D-S5-6):
- host ufficiale passato come ``host_atteso`` a ogni chiamata → la validazione
  host su URL iniziale e su OGNI hop, più il check SSRF sull'IP, è già di
  ``fetch_guardato``: l'adapter **non** duplica alcun controllo host/redirect;
- ``max_bytes`` distinti — piccolo per il JSON REST, ampio per l'HTML;
- ``consentito=False`` (rate-limit/budget) → **miss** (``()``/``None``), senza
  retry autonomo: il retry/backoff è della politica, non dell'adapter;
- ``fetched is None`` o payload non decodificabile / JSON malformato → miss;
- l'endpoint REST è costruito dall'adapter WP (``base_url`` = collezione REST),
  mai dal transport comune, che resta neutro rispetto alla piattaforma.
"""

from __future__ import annotations

import json
from typing import Callable, Protocol
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


def candidato_da_voce_wp(voce: object) -> ServiceCandidate | None:
    """Un ``ServiceCandidate`` da una voce REST WP, o ``None`` se malformata.

    Id stabile, titolo dal ``rendered``, url dal ``link``; qualunque campo
    assente/errato → scarto (mai alzare)."""
    if not isinstance(voce, dict):
        return None
    titolo_raw = voce.get("title")
    titolo = titolo_raw.get("rendered") if isinstance(titolo_raw, dict) else titolo_raw
    try:
        return ServiceCandidate(
            native_id=str(int(voce["id"])),
            title=str(titolo).strip(),
            url=str(voce["link"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def candidato_da_voce_wp_custom(voce: object) -> ServiceCandidate | None:
    """Un ``ServiceCandidate`` da una voce REST WP **dialetto B**, o ``None``.

    Alcuni comuni servono lo stesso tema (Design Comuni) attraverso un
    controller REST custom che *sovrascrive* ``wp/v2/servizi``: invece degli
    oggetti standard restituisce le righe grezze del post — chiavi ``ID`` /
    ``post_title`` / ``guid`` (non ``id`` / ``title.rendered`` / ``link``) — e
    ignora ``search`` / ``per_page`` / ``_fields`` lato server (dump completo).
    ``guid`` è un URL assoluto fornito dal server. Campo assente/errato →
    scarto (mai alzare); l'host guard e il recogniser condivisi filtrano poi un
    url off-host o un titolo non confermante, esattamente come per lo standard.
    """
    if not isinstance(voce, dict):
        return None
    try:
        return ServiceCandidate(
            native_id=str(int(voce["ID"])),
            title=str(voce["post_title"]).strip(),
            url=str(voce["guid"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def raccogli_candidati_wp(
    dati: object, rileggi_grezzo: "Callable[[], object]"
) -> tuple[ServiceCandidate, ...]:
    """Candidati WP: prima lo standard, poi il fallback dialetto B se serve.

    La ricerca «slim» (``_fields=id,title,link``) si legge come standard. Se
    produce ≥1 candidato è autoritativa e **non** si fa una seconda richiesta —
    byte-identica al comportamento pre-dialetto: lo standard non paga nulla.

    Un controller dialetto B risponde alla slim con una lista **non vuota** di
    righe non-standard (dal vivo: ``[[], [], …]`` array vuoti, perché ``_fields``
    è ignorato) → 0 candidati standard da un payload non vuoto. **Solo** in quel
    caso si fa una richiesta in più senza ``_fields`` (``rileggi_grezzo``) e la
    si legge con la forma dialetto B. Un ``[]`` genuino resta un miss onesto a
    una sola richiesta (nessun fallback su catalogo davvero vuoto).
    """
    if not isinstance(dati, list):
        return ()
    standard = tuple(
        c for c in (candidato_da_voce_wp(v) for v in dati) if c is not None
    )
    if standard or not dati:
        return standard
    grezzo = rileggi_grezzo()
    if not isinstance(grezzo, list):
        return ()
    return tuple(
        c for c in (candidato_da_voce_wp_custom(v) for v in grezzo) if c is not None
    )


class _DiscoveryStrategy(Protocol):
    """La sola logica per-famiglia: da un entry point a candidati, usando i
    primitivi di rete del transport comune. Net-free rispetto a httpx (il
    transport media tutto)."""

    def scopri_servizi(
        self,
        transport: "EsecutoreServiceFetcher",
        *,
        base_url: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        ...


class _WpDiscovery:
    """Discovery WordPress/AgID: un solo ``GET`` REST ``?search=`` deterministico.

    ``base_url`` è la **collezione REST** già composta dal connettore WP
    (``{sito}/wp-json/wp/v2/{rest_base}``): il transport comune non conosce
    ``rest_base``. Nessun fan-out."""

    def scopri_servizi(
        self,
        transport: "EsecutoreServiceFetcher",
        *,
        base_url: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        base = base_url.rstrip("/")
        host_atteso = host_senza_www(urlparse(base_url).netloc.lower())
        slim = urlencode({"search": term, "per_page": limit, "_fields": "id,title,link"})
        dati = transport.scarica_json(url=f"{base}?{slim}", host_atteso=host_atteso)

        def _rileggi_grezzo() -> object | None:
            # Solo se lo standard è vuoto-ma-non-``[]`` (dialetto B): una GET in
            # più senza ``_fields`` (che il controller custom svuoterebbe).
            grezzo = urlencode({"search": term, "per_page": limit})
            return transport.scarica_json(url=f"{base}?{grezzo}", host_atteso=host_atteso)

        return raccogli_candidati_wp(dati, _rileggi_grezzo)


class EsecutoreServiceFetcher:
    """Transport comune: i primitivi di rete guardati dall'``EsecutoreFetch``.

    Non fa discovery da solo: ``.con(strategia)`` lo compone con una strategia
    per-famiglia e restituisce un ``ServiceFetcher`` completo. Il fetch reale è
    mediato dalla ``PoliticaFetch`` (budget/rate-limit/backoff) via
    ``fetch_guardato``. Nessun login, nessun cookie.
    """

    def __init__(self, esecutore: EsecutoreFetch) -> None:
        self._esecutore = esecutore

    def con(self, strategia: _DiscoveryStrategy) -> "_FetcherComposto":
        """Compone questo transport con una strategia di discovery."""
        return _FetcherComposto(self, strategia)

    def scarica_json(self, *, url: str, host_atteso: str) -> object | None:
        """Un ``GET`` guardato con cap REST; JSON decodificato o ``None`` (miss).

        Host già normalizzato dal chiamante (strategia). Non alza mai."""
        esito = self._esecutore.esegui(
            url, timeout=_TIMEOUT_S, max_bytes=_MAX_BYTES_REST, host_atteso=host_atteso
        )
        corpo = _bytes_di(esito)
        if corpo is None:
            return None
        try:
            return json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
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


class _FetcherComposto:
    """Il ``ServiceFetcher`` finale: transport comune + una strategia. Espone la
    firma neutra del Protocol; la strategia decide REST vs scrape."""

    def __init__(self, transport: EsecutoreServiceFetcher, strategia: _DiscoveryStrategy) -> None:
        self._transport = transport
        self._strategia = strategia

    def scopri_servizi(
        self, *, base_url: str, term: str, limit: int
    ) -> tuple[ServiceCandidate, ...]:
        return self._strategia.scopri_servizi(
            self._transport, base_url=base_url, term=term, limit=limit
        )

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        return self._transport.leggi_pagina(url=url, official_host=official_host)
