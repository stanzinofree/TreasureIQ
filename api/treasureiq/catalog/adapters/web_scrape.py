"""Adapter seam for data recovered by the universal web-scraping engine.

The adapter deliberately does not perform HTTP requests. Scraping, source
ownership checks, throttling and extraction belong to the engine; this class
only normalizes its records to the same closed contract used by direct APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from treasureiq.catalog.contracts import AccessMode, FreshnessStatus, Surface
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataBatch,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
    TransportMeta,
)
from treasureiq.catalog.plugins import CapabilityManifest, PluginManifest
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore

WEB_SCRAPE_VERSION = "1"
WEB_SCRAPE_MANIFEST = PluginManifest(
    plugin_id="web_scrape",
    version=WEB_SCRAPE_VERSION,
    contract_version="catalog.v1",
    platforms=("*",),
    capabilities=tuple(
        CapabilityManifest(
            surface=surface,
            capability=capability,
            allowed_modes=(AccessMode.INDIRECT,),
            priority=priority,
        )
        for surface, capability, priority in (
            (Surface.ORDINARY_DATA, "services", 110),
            (Surface.ORDINARY_DATA, "offices", 120),
            (Surface.ORDINARY_DATA, "contacts", 130),
            (Surface.TRANSPARENCY, "transparency", 140),
        )
    ),
)


class WebScrapeAdapter:
    """Normalize records already extracted from a public municipal page."""

    name = "web_scrape"
    version = WEB_SCRAPE_VERSION
    manifest = WEB_SCRAPE_MANIFEST

    def supports(self, platform_id: str, surface: str) -> bool:
        return self.manifest.supports_platform(platform_id) and self.manifest.supports(
            surface=surface
        )

    def read(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
        records: tuple[dict[str, Any], ...] = (),
    ) -> DataBatch:
        if request.source_id != mappa.codice_istat:
            raise ValueError("request.source_id does not match the measured source")

        bounded_records = records[: request.limits.max_records]
        evidence = tuple(
            EvidenceRef(evidence_id=str(record["url"]), field="url")
            for record in bounded_records
            if record.get("url")
        )
        return DataBatch(
            request_id=request.request_id,
            status=DataStatus.FULFILLED if bounded_records else DataStatus.EMPTY,
            access_mode=AccessMode.INDIRECT,
            source_id=request.source_id,
            surface=request.surface,
            capability=request.capability,
            records=bounded_records,
            evidence=evidence,
            freshness=Freshness(
                status=FreshnessStatus.LIVE if bounded_records else FreshnessStatus.UNKNOWN,
                retrieved_at=datetime.now(timezone.utc) if bounded_records else None,
            ),
            limitations=(
                "I record devono provenire dal motore di scraping; l'adapter non effettua fetch.",
            ),
            transport=TransportMeta(from_cache=False),
            connector=ConnectorRef(name=self.name, version=WEB_SCRAPE_VERSION),
        )
