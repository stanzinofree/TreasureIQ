"""Pilot service connector for the WordPress/AgID platform family (Slice 4).

Given a recognised ``ServiceKey``, it runs one deterministic REST search on the
comune's service CPT, confirms the single matching service by re-running the
shared recogniser on the candidate titles, reads that one page for evidence,
and emits exactly one ``ServiceReference`` with its access options.

Boundaries (from the Slice 4 contract):
- exactly one confirmed candidate, or ``NOT_FOUND`` (0/≥2 are never guessed);
- ``service_id`` is ``{source_id}:wp:{native_id}`` (``native_id`` = ``str(id)``) — never the title;
- ``access_mode`` is ``MEDIATED`` (TIQ relays the comune's data, is not it);
- no invented URLs, no login/cookies, no merge with inventoried SP entrypoints
  (that is Slice 6); the authenticated option, if any, comes only from evidence
  on the service page itself.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from treasureiq.catalog.adapters.wordpress_agid import WORDPRESS_AGID_MANIFEST
from treasureiq.catalog.data_contracts import ConnectorRef
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.connettore_base import (
    DiscoveryTarget,
    _ServiceConnectorBase,
)
from treasureiq.catalog.service_contracts import SERVICE_SEARCH_TERM, ServiceKey
from treasureiq.ingest.base import USER_AGENT
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www

#: The WordPress/AgID platform ids this pilot serves (single source of truth:
#: the existing adapter manifest).
_PIATTAFORME_WP_AGID = frozenset(WORDPRESS_AGID_MANIFEST.platforms)

#: Default page size for the single ``?search=`` query.
_LIMITE_RICERCA = 20

_CONNECTOR = ConnectorRef(name="wordpress_agid_service", version="1")


class WordPressAgidServiceConnector(_ServiceConnectorBase):
    """Resolve a ``ServiceKey`` to one ``ServiceReference`` on WP/AgID portals.

    The whole resolution body (confirm, options, esito) is shared in
    ``_ServiceConnectorBase``; this subtype only pins the platform gate, the
    ``service_id`` prefix and how the REST discovery target is composed."""

    name = "wordpress_agid_service"
    version = "1"
    _CONNECTOR = _CONNECTOR
    _PIATTAFORME = _PIATTAFORME_WP_AGID
    _PREFISSO = "wp"
    _PROVIDER_PLATFORM = "wordpress_agid"
    _LIMITE_RICERCA = _LIMITE_RICERCA

    def _discovery_target(self, mappa, service_key: ServiceKey) -> DiscoveryTarget | None:
        base = _base_con_schema(getattr(mappa, "sito", None))
        if base is None or not mappa.servizi.esposto:
            # No site, or the service CPT is not exposed for this comune.
            return None
        # rest_base stays inside the WP adapter: fold it into the REST collection
        # entry point here, so the neutral fetcher signature never sees it. In
        # practice every scanned comune's service CPT is "servizi" (invariant),
        # but a per-comune override is still honoured.
        rest_base = mappa.servizi.rest_base or "servizi"
        entry = f"{base.rstrip('/')}/wp-json/wp/v2/{rest_base}"
        return DiscoveryTarget(entry, SERVICE_SEARCH_TERM[service_key], urlparse(base).netloc)


#: How many redirect hops to follow manually on a page fetch before giving up.
_MAX_REDIRECT = 5


class HttpxServiceFetcher:
    """Real ``ServiceFetcher`` over httpx.  The connector logic is covered by a
    stub; this class owns the HTTP boundary, so its host discipline IS tested
    (via an injected transport).  No login, no cookies.

    The page fetch never lets httpx follow redirects on its own: a comune page
    could 30x to an external host and httpx would happily read it.  Redirects
    are followed manually and the host is re-checked on every hop and on the
    final URL, so an off-host redirect ends the fetch (``None``) instead of
    leaking a third party's HTML."""

    def __init__(
        self, *, timeout: float = 10.0, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._timeout = timeout
        self._transport = transport

    def _client(self, *, follow_redirects: bool) -> httpx.Client:
        return httpx.Client(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=follow_redirects,
            transport=self._transport,
        )

    def scopri_servizi(
        self,
        *,
        base_url: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        # base_url is the REST collection endpoint already composed by the WP
        # connector ({site}/wp-json/wp/v2/{rest_base}); rest_base stays inside the
        # WP adapter, never in the neutral fetcher signature.
        url = base_url
        # base_url comes from the trusted mappa, but the REST endpoint's own HTTP
        # redirects are remote-network behaviour: a 30x could steer the JSON read
        # to an unauthorised host.  Same discipline as the page fetch — redirects
        # followed manually, host re-checked on every hop and the final URL.
        host_ufficiale = _host_senza_www(urlparse(base_url).netloc.lower())
        resp = self._get_verificato(
            url,
            host_ufficiale=host_ufficiale,
            params={"search": term, "per_page": limit, "_fields": "id,title,link"},
        )
        if resp is None or resp.status_code != 200:
            return ()
        try:
            dati = resp.json()
        except ValueError:
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

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        host_ufficiale = _host_senza_www(official_host.lower())
        resp = self._get_verificato(url, host_ufficiale=host_ufficiale)
        if resp is None or resp.status_code != 200:
            return None
        return resp.text

    def _get_verificato(
        self,
        url: str,
        *,
        host_ufficiale: str,
        params: dict | None = None,
    ) -> httpx.Response | None:
        """GET ``url`` never letting httpx follow redirects on its own: a remote
        30x could steer the read to an external host.  Redirects are followed
        manually with the host re-checked on the initial URL, on every hop, and
        on the final URL — an off-host redirect ends the fetch (``None``), the
        response is never read.  Applies to both the REST search and the page
        fetch, so neither reads a body from an unauthorised host."""
        if not host_ufficiale or _host_senza_www(urlparse(url).netloc.lower()) != host_ufficiale:
            return None
        # Bake params into the first URL; on redirects the server's Location
        # carries the query, so re-passing params would duplicate it.
        corrente = str(httpx.URL(url, params=params)) if params else url
        try:
            with self._client(follow_redirects=False) as client:
                for _ in range(_MAX_REDIRECT + 1):
                    resp = client.get(corrente)
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            return None
                        corrente = str(httpx.URL(corrente).join(location))
                        # Re-check the host on EVERY hop: an off-host redirect
                        # ends the fetch, it is never read.
                        if _host_senza_www(urlparse(corrente).netloc.lower()) != host_ufficiale:
                            return None
                        continue
                    return resp
            return None  # too many redirects
        except httpx.HTTPError:
            return None
