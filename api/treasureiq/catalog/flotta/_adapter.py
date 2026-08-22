"""Adapter gate for the fleet connectors.

``CatalogRuntime.execute`` resolves a connector AND an adapter and returns nothing
unless both are present — the adapter is a gate, while the connector does the
projection.  One adapter serves the whole fleet because the projection is on the
``EsitoConnettore`` contract, not on a platform (see :mod:`._projection`).  The
per-platform independence the fleet needs — version, registration, fingerprint
stamp — lives in the connector units, not in this gate.

``read`` exists for any caller that drives an adapter directly; the runtime path
uses ``connector.retrieve`` and this adapter only to pass the gate.
"""

from __future__ import annotations

from typing import Any

from treasureiq.catalog.contracts import AccessMode, Surface
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataBatch,
    DataRequest,
    TransportMeta,
)
from treasureiq.catalog.flotta import _projection
from treasureiq.catalog.plugins import CapabilityManifest, PluginManifest
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore

#: Platforms whose ``EsitoConnettore`` carries a flat ``uffici`` list the fleet
#: can project.  eGov/HGATE (``aree_amministrative``) and URBI (no ordinary-data
#: connector) are excluded on purpose — the v0 office rail does not serve them
#: either, so covering them is an enhancement beyond parity, its own slice later.
FLOTTA_PLATFORMS = ("municipium", "comweb", "peopleweb")

FLOTTA_ADAPTER_VERSION = "1.0.0"

FLOTTA_MANIFEST = PluginManifest(
    plugin_id="flotta",
    version=FLOTTA_ADAPTER_VERSION,
    contract_version="catalog.v1",
    platforms=FLOTTA_PLATFORMS,
    capabilities=(
        CapabilityManifest(
            surface=Surface.ORDINARY_DATA,
            capability="offices",
            allowed_modes=(AccessMode.MEDIATED,),
            priority=20,
        ),
        CapabilityManifest(
            surface=Surface.ORDINARY_DATA,
            capability="contacts",
            allowed_modes=(AccessMode.MEDIATED,),
            priority=30,
        ),
        CapabilityManifest(
            surface=Surface.TRANSPARENCY,
            capability="transparency",
            allowed_modes=(AccessMode.MEDIATED,),
            priority=40,
        ),
    ),
)


class FlottaAdapter:
    """Gate + direct-read projection for the whole fleet."""

    name = "flotta"
    version = FLOTTA_ADAPTER_VERSION
    manifest = FLOTTA_MANIFEST

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

        mode = _projection.access_mode(request.surface, request.capability, esito)
        record_dicts = _projection.records(request.surface, request.capability, esito)[
            : request.limits.max_records
        ]
        fresh = _projection.freshness(
            esito.letto_il if esito else "", request.freshness.max_age_seconds
        )
        return DataBatch(
            request_id=request.request_id,
            status=_projection.status(mode, record_dicts, fresh),
            access_mode=mode,
            source_id=request.source_id,
            surface=request.surface,
            capability=request.capability,
            records=tuple(record_dicts),
            evidence=_projection.evidence(record_dicts),
            freshness=fresh,
            transport=TransportMeta(from_cache=True),
            connector=ConnectorRef(name=self.name, version=self.version),
        )
