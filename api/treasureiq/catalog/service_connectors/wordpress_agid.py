"""Pilot service connector for the WordPress/AgID platform family (Slice 4).

Given a recognised ``ServiceKey``, it runs one deterministic REST search on the
comune's service CPT, confirms the single matching service by re-running the
shared recogniser on the candidate titles, reads that one page for evidence,
and emits exactly one ``ServiceReference`` with its access options.

Boundaries (from the Slice 4 contract):
- exactly one confirmed candidate, or ``NOT_FOUND`` (0/≥2 are never guessed);
- ``service_id`` is ``{source_id}:wp:{wordpress_id}`` — never the title;
- ``access_mode`` is ``MEDIATED`` (TIQ relays the comune's data, is not it);
- no invented URLs, no login/cookies, no merge with inventoried SP entrypoints
  (that is Slice 6); the authenticated option, if any, comes only from evidence
  on the service page itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from treasureiq.catalog.adapters.wordpress_agid import WORDPRESS_AGID_MANIFEST
from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import AccessMode, CAPABILITY_SERVICES, FreshnessStatus, Surface
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
)
from treasureiq.catalog.service_connectors.base import ServiceCandidate, ServiceFetcher
from treasureiq.catalog.service_contracts import (
    SERVICE_SEARCH_TERM,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
    ServiceReference,
)
from treasureiq.catalog.service_page import EvidenceKind, leggi_pagina_servizio
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.connettore import EsitoConnettore
from treasureiq.ingest.base import USER_AGENT
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www

#: The WordPress/AgID platform ids this pilot serves (single source of truth:
#: the existing adapter manifest).
_PIATTAFORME_WP_AGID = frozenset(WORDPRESS_AGID_MANIFEST.platforms)

#: Default page size for the single ``?search=`` query.
_LIMITE_RICERCA = 20

_CONNECTOR = ConnectorRef(name="wordpress_agid_service", version="1")


class WordPressAgidServiceConnector:
    """Resolve a ``ServiceKey`` to one ``ServiceReference`` on WP/AgID portals."""

    name = "wordpress_agid_service"
    version = "1"

    def __init__(self, fetcher: ServiceFetcher) -> None:
        self._fetcher = fetcher

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        # Barrier vs the ServicePortalConnettore: only ordinary-data services on
        # a WordPress/AgID platform.
        return (
            request.surface is Surface.ORDINARY_DATA
            and request.capability == CAPABILITY_SERVICES
            and platform_id in _PIATTAFORME_WP_AGID
        )

    def retrieve(
        self,
        request: DataRequest,
        *,
        mappa,
        esito: EsitoConnettore | None,
    ) -> ConnectorResult:
        now = datetime.now(timezone.utc)

        if request.source_id != mappa.codice_istat:
            # The measured source must be the one requested: the service_id is
            # built from source_id, so a mismatch would mint a false identity.
            raise ValueError("request.source_id does not match the measured source")

        service_key = self._service_key(request)
        if service_key is None:
            return self._esito(request, now, DataStatus.NOT_FOUND, AccessMode.UNAVAILABLE)

        base = _base_con_schema(getattr(mappa, "sito", None))
        if base is None or not mappa.servizi.esposto:
            # No site, or the service CPT is not exposed for this comune.
            return self._esito(request, now, DataStatus.NOT_SUPPORTED, AccessMode.UNAVAILABLE)

        rest_base = mappa.servizi.rest_base or "servizi"
        official_host = urlparse(base).netloc

        candidati = self._fetcher.cerca_servizi(
            base_url=base,
            rest_base=rest_base,
            term=SERVICE_SEARCH_TERM[service_key],
            limit=_LIMITE_RICERCA,
        )
        confermati = self._confermati(candidati, service_key)
        if len(confermati) != 1:
            # 0 → honest miss; ≥2 → ambiguous, the choice belongs to a higher
            # level, never an implicit pick here.
            return self._esito(request, now, DataStatus.NOT_FOUND, AccessMode.MEDIATED)

        candidato = confermati[0]
        opzioni = self._opzioni(candidato, official_host)
        reference = ServiceReference(
            service_id=f"{request.source_id}:wp:{candidato.wordpress_id}",
            title=candidato.title,
            source_url=candidato.url,
            options=opzioni,
            discovered_from=Surface.ORDINARY_DATA,
            provider_platform="wordpress_agid",
            discovered_at=now,
        )
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=DataStatus.FULFILLED,
            access_mode=AccessMode.MEDIATED,
            service_references=(reference,),
            evidence=tuple(
                EvidenceRef(evidence_id=str(opzione.url), field="url") for opzione in opzioni
            ),
            freshness=Freshness(status=FreshnessStatus.LIVE, retrieved_at=now),
            connector=_CONNECTOR,
            retrieved_at=now,
        )

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _service_key(request: DataRequest) -> ServiceKey | None:
        raw = request.selection.get("service_key")
        if not raw:
            return None
        try:
            return ServiceKey(raw)
        except ValueError:
            return None

    @staticmethod
    def _confermati(
        candidati: tuple[ServiceCandidate, ...], service_key: ServiceKey
    ) -> tuple[ServiceCandidate, ...]:
        # Confirm each candidate by the SHARED recogniser on its title: same
        # key, unambiguous (the recogniser returns None on conflict), no
        # nearest-neighbour.  A candidate that does not confirm is dropped.
        return tuple(c for c in candidati if riconosci_service_key(c.title) is service_key)

    def _opzioni(
        self, candidato: ServiceCandidate, official_host: str
    ) -> tuple[ServiceAccessOption, ...]:
        # INFORMATION is always present: the service page is the cited source.
        opzioni: list[ServiceAccessOption] = [
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION,
                url=candidato.url,
                source_url=candidato.url,
            )
        ]
        html = self._fetcher.leggi_pagina(url=str(candidato.url), official_host=official_host)
        if not html:
            return tuple(opzioni)

        pagina = leggi_pagina_servizio(
            html, page_url=str(candidato.url), official_host=official_host
        )
        for link in pagina.links:
            if link.kind is EvidenceKind.DOWNLOAD:
                opzioni.append(
                    ServiceAccessOption(
                        mode=ServiceAccessMode.DOWNLOAD,
                        url=link.url,
                        source_url=candidato.url,
                    )
                )
            elif link.kind is EvidenceKind.AUTHENTICATED_ONLINE:
                opzioni.append(
                    ServiceAccessOption(
                        mode=ServiceAccessMode.AUTHENTICATED_ONLINE,
                        url=link.url,
                        source_url=candidato.url,
                        requires_authentication=True,
                        authentication=link.authentication,
                    )
                )
        return tuple(opzioni)

    @staticmethod
    def _esito(
        request: DataRequest,
        now: datetime,
        status: DataStatus,
        access_mode: AccessMode,
    ) -> ConnectorResult:
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=status,
            access_mode=access_mode,
            freshness=Freshness(status=FreshnessStatus.LIVE, retrieved_at=now),
            connector=_CONNECTOR,
            retrieved_at=now,
        )


class HttpxServiceFetcher:
    """Real ``ServiceFetcher`` over httpx.  Not exercised by golden tests (it is
    the only part that touches the network); the connector logic is tested with
    a stub.  No login, no cookies; the official-host guard runs before any page
    fetch."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def cerca_servizi(
        self,
        *,
        base_url: str,
        rest_base: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        url = f"{base_url.rstrip('/')}/wp-json/wp/v2/{rest_base}"
        try:
            with self._client() as client:
                resp = client.get(
                    url,
                    params={"search": term, "per_page": limit, "_fields": "id,title,link"},
                )
                resp.raise_for_status()
                dati = resp.json()
        except (httpx.HTTPError, ValueError):
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
                wordpress_id=int(voce["id"]),
                title=str(titolo).strip(),
                url=str(voce["link"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        # Host guard: only read a page on the comune's own host (SSRF).
        host_pagina = _host_senza_www(urlparse(url).netloc.lower())
        host_ufficiale = _host_senza_www(urlparse(f"//{official_host}").netloc.lower())
        if not host_pagina or host_pagina != host_ufficiale:
            return None
        try:
            with self._client() as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError:
            return None
