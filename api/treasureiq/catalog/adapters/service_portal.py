"""Catalog adapter gating the SERVICE_PORTAL surface.

The runtime resolves an adapter as the platform-level *gate* for a request and
builds the batch from the connector result.  This adapter declares that the
service-portal surface is served for every platform in the ``INDIRECT`` mode
(TIQ points to the official portal, it never authenticates).  Its ``read`` is a
pure projection kept for parity with the other adapters; it invents no records.
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

SERVICE_PORTAL_ADAPTER_VERSION = "1"

SERVICE_PORTAL_MANIFEST = PluginManifest(
    plugin_id="service_portal",
    version=SERVICE_PORTAL_ADAPTER_VERSION,
    contract_version="catalog.v1",
    platforms=("*",),
    capabilities=(
        CapabilityManifest(
            surface=Surface.SERVICE_PORTAL,
            capability="authenticated_service",
            allowed_modes=(AccessMode.INDIRECT,),
        ),
    ),
)


class ServicePortalAdapter:
    name = "service_portal"
    version = SERVICE_PORTAL_ADAPTER_VERSION
    manifest = SERVICE_PORTAL_MANIFEST

    def supports(self, platform_id: str, surface: str) -> bool:
        return surface == Surface.SERVICE_PORTAL.value

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
                status=FreshnessStatus.FRESH if bounded_records else FreshnessStatus.UNKNOWN,
                retrieved_at=datetime.now(timezone.utc) if bounded_records else None,
            ),
            limitations=(
                "L'adapter proietta solo puntatori ufficiali: nessun accesso autenticato.",
            ),
            transport=TransportMeta(from_cache=True),
            connector=ConnectorRef(name=self.name, version=SERVICE_PORTAL_ADAPTER_VERSION),
        )
