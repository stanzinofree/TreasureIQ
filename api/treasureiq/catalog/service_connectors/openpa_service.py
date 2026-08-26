"""OpenPA/OpenCity service connector (Ramo 3, Connettore #3).

Platform family = OpenCity Labs on eZ Publish (extension
``openpa_bootstrapitalia``), NOT Plone/Maggioli.  The service catalog UI
(``/Servizi``) is rendered client-side, so a static fetch sees empty shells;
the machine-readable layer is the OpenData REST endpoint
``{sito}/opendata/api/content/search/`` querying the eZ Find DSL.

Contract/invariants/options live in ``_ServiceConnectorBase``; this module fixes
only the OpenPA specifics:
- ``_discovery_target``: the eZ Find search endpoint + the shared search term;
- ``_EzFindDiscovery`` (injected via the shared ``EsecutoreServiceFetcher``):
  builds one deterministic ``q`` query and parses the JSON search hits.

Three OpenPA facts drove the design, each verified live on Storo (022183, TN)
and Lodrino (017090, BS):
- ``q`` is an eZ Find DSL, not free text: full-text is the literal field ``q``
  with a single-quoted value — ``q = '<testo>' and limit <n>``.  The value is
  escaped (``\\`` and ``'``) exactly as the portal's own query-builder does; a
  bare token or a double-quoted value is a 400.
- the query does NOT restrict ``classes``: TARI is published in the ``document``
  class, not ``public_service``, so pinning a class would drop it.  The shared
  recogniser confirms the single service by title afterwards (I-6), so the wider
  recall costs nothing in correctness.
- the citizen URL is NOT in ``link`` (that is the API ``read/<id>``): it is the
  SEO path ``extradata[lang].urlAlias``, resolved against the site root.

Honest known gap (no nearest-neighbour, I-1): in Trentino IMU is titled
"IMIS"; the shared term ``imu`` and the ``imu`` recogniser marker do not match
it, so IMU there resolves NOT_FOUND rather than guessing a neighbour.  Teaching
the shared recogniser about IMIS is a separate change (blast radius across
families) and is deliberately out of this slice.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlparse

from treasureiq.catalog.data_contracts import ConnectorRef
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.connettore_base import (
    DiscoveryTarget,
    _ServiceConnectorBase,
)
from treasureiq.catalog.service_connectors.esecutore_fetcher import EsecutoreServiceFetcher
from treasureiq.catalog.service_contracts import SERVICE_SEARCH_TERM, ServiceKey
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www

#: The OpenData REST search endpoint, appended to the comune's site root.
_ENDPOINT_RICERCA = "/opendata/api/content/search/"

#: Content language of the schede; the ``name``/``urlAlias`` used to build the
#: candidate live under this key.
_LINGUA = "ita-IT"

_CONNECTOR = ConnectorRef(name="openpa_service", version="1")


def _valore_q(term: str) -> str:
    """Escape ``term`` for an eZ Find single-quoted ``q`` value.

    The portal's own query-builder backslash-escapes; a literal apostrophe in
    the value (the shared term ``carta d'identità`` has one) is a 400 otherwise.
    Backslash first, then the quote, so an escaped quote is never re-escaped."""
    return term.replace("\\", "\\\\").replace("'", "\\'")


def costruisci_query_ezfind(term: str, *, limit: int) -> str:
    """The one deterministic eZ Find query for a term.

    No ``classes`` restriction (TARI lives in ``document``, not
    ``public_service``); recall is narrowed by the term and then confirmed by
    the recogniser on the title, never widened to a neighbour."""
    return f"q = '{_valore_q(term)}' and limit {int(limit)}"


def candidato_da_hit_ezfind(hit: object, *, site_base: str) -> ServiceCandidate | None:
    """A ``ServiceCandidate`` from one eZ Find search hit, or ``None`` if malformed.

    ``native_id`` = the stable eZ node id (``metadata.id``); title =
    ``metadata.name[ita-IT]``; url = the SEO ``extradata[ita-IT].urlAlias``
    resolved against the site root — never ``link`` (that is ``read/<id>``, the
    API, not a citizen page).  Any missing/ill-typed field → discard (never
    raise): the host guard and the recogniser filter the rest upstream."""
    if not isinstance(hit, dict):
        return None
    metadata = hit.get("metadata")
    extradata = hit.get("extradata")
    if not isinstance(metadata, dict) or not isinstance(extradata, dict):
        return None
    nome = metadata.get("name")
    if isinstance(nome, dict):
        nome = nome.get(_LINGUA)
    lingua = extradata.get(_LINGUA)
    alias = lingua.get("urlAlias") if isinstance(lingua, dict) else None
    if not nome or not alias:
        return None
    try:
        native_id = str(int(metadata["id"]))
    except (KeyError, TypeError, ValueError):
        return None
    # eZ content class of this hit (``public_service``/``document``/``article``/…);
    # kept on the candidate so the connector's class-aware allow-list can gate on
    # it BEFORE the exactly-1 gate.  Missing/ill-typed → ``None`` (dropped by the
    # allow-list: an unclassifiable hit is never a confirmed service).
    classe = metadata.get("classIdentifier")
    classe = classe if isinstance(classe, str) and classe else None
    # urlAlias is a site-relative SEO path; resolve it against the site root.
    url = urljoin(site_base.rstrip("/") + "/", str(alias).lstrip("/"))
    try:
        return ServiceCandidate(
            native_id=native_id,
            title=unescape(str(nome)).strip(),
            url=url,
            native_class=classe,
        )
    except ValueError:
        return None


def raccogli_candidati_ezfind(payload: object, *, site_base: str) -> tuple[ServiceCandidate, ...]:
    """Candidates from an eZ Find ``content/search`` JSON payload.

    Reads ``searchHits``; a missing/ill-typed payload or list is an honest empty
    result (``()``), never a raise."""
    if not isinstance(payload, dict):
        return ()
    hits = payload.get("searchHits")
    if not isinstance(hits, list):
        return ()
    return tuple(
        c
        for c in (candidato_da_hit_ezfind(h, site_base=site_base) for h in hits)
        if c is not None
    )


class _EzFindDiscovery:
    """OpenPA discovery: one guarded ``GET`` on the eZ Find search endpoint.

    Net-free with respect to httpx: the shared ``EsecutoreServiceFetcher``
    mediates budget/rate-limit/redirect/host-guard (``scarica_json``); this
    strategy only composes the URL and parses the JSON hits.  ``base_url`` is the
    search endpoint the connector already built from the comune's site."""

    def scopri_servizi(
        self,
        transport: "EsecutoreServiceFetcher",
        *,
        base_url: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        parsed = urlparse(base_url)
        host = _host_senza_www(parsed.netloc.lower())
        # Site root for resolving the relative urlAlias of each hit.
        site_base = f"{parsed.scheme}://{parsed.netloc}"
        from urllib.parse import urlencode

        query = urlencode({"q": costruisci_query_ezfind(term, limit=limit)})
        payload = transport.scarica_json(url=f"{base_url}?{query}", host_atteso=host)
        return raccogli_candidati_ezfind(payload, site_base=site_base)


#: Allow-list class-aware per ServiceKey — policy misurata sul campione dei 28
#: comuni OpenPA (2026-08-26, vedi docs/workstreams/flotta-connettori/
#: proposta-filtro-class-aware-openpa.md).  Uniforme sulle 6 chiavi: ``public_service``
#: è il servizio vero; ``document`` e ``output`` restano ammessi perché su OpenPA
#: i tributi (IMU/TARI) e parte dell'anagrafe/atti vivono lì (regolamenti, moduli,
#: nodi "cosa puoi richiedere"), non in ``public_service``.  Tutto il resto —
#: ``article`` (notizie), ``channel``, ``organization``, media, … — è escluso PRIMA
#: del gate esattamente-1: era la sorgente #1 di ambiguità e di confermati-notizia.
#: NB: IMU/TARI restano strutturalmente più deboli — il rumore in ``document``/
#: ``output`` non è separabile per classe; questa allow-list lo contiene, non lo
#: risolve.  Per-key (non un set globale) così una chiave può divergere in futuro
#: senza allargare le altre.
_CLASSI_AMMESSE: dict[ServiceKey, frozenset[str]] = {
    ServiceKey.CARTA_IDENTITA: frozenset({"public_service", "document", "output"}),
    ServiceKey.CAMBIO_RESIDENZA: frozenset({"public_service", "document", "output"}),
    ServiceKey.ACCESSO_ATTI: frozenset({"public_service", "document", "output"}),
    ServiceKey.STATO_CIVILE: frozenset({"public_service", "document", "output"}),
    ServiceKey.TRIBUTI_IMU: frozenset({"public_service", "document", "output"}),
    ServiceKey.TRIBUTI_TARI: frozenset({"public_service", "document", "output"}),
}

#: Layer B — detrito amministrativo di back-office che un cittadino non cerca mai
#: come "il servizio": regolamenti, delibere, determine, tariffe/aliquote, ruoli,
#: impegni di spesa, verbali, registri (il *registro* degli accessi non è il
#: servizio di accesso).  Substring, confronto lowercase.  Deliberatamente NON
#: include modulo/modello/istanza/domanda/richiesta: quelli SONO artefatti
#: azionabili (moduli da scaricare, richieste) e restano candidati validi.
#: Applicato SOLO come tie-break fra ≥2 match del recogniser — mai per rimuovere
#: un match unico: un servizio già risolto esattamente-1 non viene toccato
#: (vedi il golden dei 39 casi in test).
_STOPLIST_DETRITO: tuple[str, ...] = (
    "regolament", "delibera", "deliber", "determina", "aliquot", "tariff",
    "approvazione", "impegno di spesa", "accertament", "affidament",
    "comunicato", "verbale", "assunzione impegno", "a contrarre", "registro",
)
#: Token stand-alone (evita il match dentro parole non correlate): sigle e parole
#: brevi di atti amministrativi.  ``ruolo`` = ruolo tributario; ``det``/``delib``
#: = sigle di determina/delibera; ``imp`` = impegno.
_DETRITO_RX = re.compile(r"\b(ruolo|det|delib|imp)\b", re.IGNORECASE)

#: Layer 0 — marcatori dominio-negativi per chiave: un titolo che il recogniser
#: condiviso matcha ma che appartiene a un dominio amministrativo diverso.  Es.
#: "cambio residenza taxi" = spostamento di una licenza taxi, non l'anagrafe del
#: cittadino.  OpenPA-local, recogniser intatto; esclusione hard PRIMA del gate.
#: Criterio "stesso dominio": scegliamo di NON confermare un match fuori-dominio,
#: non è una certezza semantica del titolo.
_MARCATORI_NEGATIVI: dict[ServiceKey, tuple[str, ...]] = {
    ServiceKey.CAMBIO_RESIDENZA: ("taxi",),
    ServiceKey.STATO_CIVILE: ("taxi",),
    ServiceKey.ACCESSO_ATTI: ("taxi",),
}


def _e_detrito(title: str) -> bool:
    """True se il titolo è detrito amministrativo di back-office (Layer B).

    Substring per le forme lunghe (regolamento, determina, …) più i token
    stand-alone brevi (ruolo, det, delib, imp).  Puro, deterministico."""
    t = title.lower()
    if any(s in t for s in _STOPLIST_DETRITO):
        return True
    return bool(_DETRITO_RX.search(t))


class OpenPAServiceConnector(_ServiceConnectorBase):
    """Resolve a ``ServiceKey`` to one ``ServiceReference`` on OpenPA/OpenCity portals.

    The whole resolution body (confirm, options, esito) is shared in
    ``_ServiceConnectorBase``; this subtype only pins the platform gate, the
    ``service_id`` prefix and how the eZ Find discovery target is composed."""

    name = "openpa_service"
    version = "1"
    _CONNECTOR = _CONNECTOR
    _PIATTAFORME = frozenset({Piattaforma.OPENPA.value})
    _PREFISSO = "openpa"
    _PROVIDER_PLATFORM = "openpa"

    def _discovery_target(self, mappa, service_key: ServiceKey) -> DiscoveryTarget | None:
        base = _base_con_schema(getattr(mappa, "sito", None))
        if base is None:
            # No site: the platform is not servable for this comune.
            return None
        entry = f"{base.rstrip('/')}{_ENDPOINT_RICERCA}"
        return DiscoveryTarget(entry, SERVICE_SEARCH_TERM[service_key], urlparse(base).netloc)

    def _filtra_candidati(
        self,
        candidati: tuple[ServiceCandidate, ...],
        service_key: ServiceKey,
    ) -> tuple[ServiceCandidate, ...]:
        """Filtro OpenPA-local a strati, PRIMA di ``_confermati`` e del gate 0/≥2.

        Ordine (tutto OpenPA-local, recogniser condiviso e contratti INTATTI):

        - **classe** (allow-list ``_CLASSI_AMMESSE``): tiene solo le classi eZ
          ammesse per la key; ``article``/``channel``/``organization``/media
          fuori.  ``native_class`` None → scartato (non classificabile ≠ servizio).
        - **Layer 0** (``_MARCATORI_NEGATIVI``): via i titoli in un dominio
          amministrativo diverso (es. residenza *taxi* per l'anagrafe).
        - **disambiguazione SOLO fra ≥2 match del recogniser**: sotto i 2 match il
          set passa intatto e sono ``_confermati`` + il gate 0/≥2 a risolvere — un
          match unico resta confermato, MAI toccato (golden dei 39).  Il recogniser
          è *chiamato*, non modificato.
        - **Layer B** (``_e_detrito``): fra i ≥2 match, via il detrito
          amministrativo (regolamenti/determine/tariffe/registri).  Se ne resta
          uno solo → quello; se non ne resta nessuno (solo detrito) → il set
          intatto resta ambiguo → NOT_FOUND onesto.
        - **Layer A** (priorità classe): fra i match non-detrito, se ne esiste
          **uno solo** ``public_service`` vince su ``document``/``output``.  È il
          criterio "stesso dominio" (preferiamo la classe che OpenPA usa per la
          scheda-servizio), NON una certezza semantica; se restano ≥2
          ``public_service`` sono servizi davvero distinti → NOT_FOUND (I-1, la
          scelta è di un livello superiore, mai un nearest-neighbour qui).

        NB host guard: il tie-break precede l'host guard di ``_confermati``; su
        OpenPA l'endpoint è mono-sito (0 fallimenti host nel campione) quindi
        innocuo, e comunque fallisce SICURO — un ``public_service`` su host
        esterno verrebbe scartato da ``_confermati`` (→ NOT_FOUND), mai confermato.
        """
        ammesse = _CLASSI_AMMESSE.get(service_key, frozenset())
        c = tuple(x for x in candidati if x.native_class in ammesse)

        neg = _MARCATORI_NEGATIVI.get(service_key, ())
        if neg:
            c = tuple(x for x in c if not any(n in x.title.lower() for n in neg))

        matched = tuple(x for x in c if riconosci_service_key(x.title) is service_key)
        if len(matched) <= 1:
            # 0 o 1 match: nessuna ambiguità da sciogliere.  Lascia decidere
            # _confermati (recogniser + host) e il gate — il match unico è confermato.
            return c

        non_detrito = tuple(x for x in matched if not _e_detrito(x.title))
        if len(non_detrito) == 1:
            return non_detrito
        if not non_detrito:
            # Solo detrito: nessun servizio azionabile → resta ambiguo (NOT_FOUND).
            return matched

        ps = tuple(x for x in non_detrito if x.native_class == "public_service")
        if len(ps) == 1:
            return ps
        return non_detrito
