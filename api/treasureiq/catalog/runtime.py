"""Deterministic execution seam joining connector, adapter and data contract."""

from __future__ import annotations

from treasureiq.catalog.adapters import AdapterRegistry, default_adapter_registry
from treasureiq.catalog.connector_defaults import default_connector_registry
from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.data_contracts import DataBatch, DataRequest
from treasureiq.catalog.data_contracts import FreshnessPolicy, RequestLimits
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore


def batch_from_connector_result(request: DataRequest, result: ConnectorResult) -> DataBatch:
    """Project acquisition output into the common batch without interpretation."""
    return DataBatch(
        request_id=request.request_id,
        status=result.status,
        access_mode=result.access_mode,
        source_id=request.source_id,
        surface=request.surface,
        capability=request.capability,
        records=result.records,
        service_references=result.service_references,
        evidence=result.evidence,
        freshness=result.freshness,
        limitations=result.limitations,
        transport=result.transport,
        connector=result.connector,
    )


class CatalogRuntime:
    """Execute one request through the two registries in a fixed order."""

    def __init__(
        self,
        *,
        connectors: ConnectorRegistry | None = None,
        adapters: AdapterRegistry | None = None,
    ) -> None:
        self.connectors = connectors or default_connector_registry()
        self.adapters = adapters or default_adapter_registry()

    def execute(
        self,
        request: DataRequest,
        *,
        platform_id: str,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> DataBatch | None:
        connector = self.connectors.resolve(request=request, platform_id=platform_id)
        adapter = self.adapters.resolve(
            platform_id=platform_id,
            surface=request.surface.value,
            capability=request.capability,
        )
        if connector is None or adapter is None:
            return None
        result = connector.retrieve(request, mappa=mappa, esito=esito)
        return batch_from_connector_result(request, result)

    def execute_fallbacks(
        self,
        *,
        source_id: str,
        platform_id: str,
        mappa: MappaConnettore,
        freshness: FreshnessPolicy,
        limits: RequestLimits,
        manifest_revision: int,
        request_prefix: str = "fallback",
    ) -> tuple[DataBatch, ...]:
        """Explicitly execute wildcard indirect requests for one source."""
        requests = self.adapters.fallback_requests_for(
            source_id=source_id,
            platform_id=platform_id,
            request_prefix=request_prefix,
            freshness=freshness,
            limits=limits,
            manifest_revision=manifest_revision,
        )
        batches: list[DataBatch] = []
        for request in requests:
            batch = self.execute(
                request,
                platform_id=platform_id,
                mappa=mappa,
                esito=None,
            )
            if batch is not None:
                batches.append(batch)
        return tuple(batches)
