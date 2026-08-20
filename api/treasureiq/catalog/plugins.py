"""Versioned plugin manifests for source adapters."""

from __future__ import annotations

from pydantic import Field

from treasureiq.catalog.contracts import AccessMode, Surface
from treasureiq.catalog.data_contracts import (
    DataRequest,
    FreshnessPolicy,
    RequestLimits,
    _StrictModel,
)


class CapabilityManifest(_StrictModel):
    surface: Surface
    capability: str = Field(min_length=1)
    allowed_modes: tuple[AccessMode, ...] = (
        AccessMode.DIRECT,
        AccessMode.MEDIATED,
        AccessMode.INDIRECT,
    )
    priority: int = Field(default=100, ge=0)


class PluginManifest(_StrictModel):
    plugin_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    capabilities: tuple[CapabilityManifest, ...] = Field(min_length=1)

    def supports(self, *, surface: str, capability: str | None = None) -> bool:
        return any(
            item.surface.value == surface
            and (capability is None or item.capability == capability)
            for item in self.capabilities
        )

    def requests(
        self,
        *,
        source_id: str,
        request_prefix: str,
        freshness: FreshnessPolicy,
        limits: RequestLimits,
        manifest_revision: int,
    ) -> tuple[DataRequest, ...]:
        ordered = sorted(
            self.capabilities,
            key=lambda item: (item.priority, item.surface.value, item.capability),
        )
        return tuple(
            DataRequest(
                request_id=f"{request_prefix}:{source_id}:{item.surface.value}:{item.capability}",
                source_id=source_id,
                surface=item.surface,
                capability=item.capability,
                freshness=freshness,
                limits=limits,
                manifest_revision=manifest_revision,
            )
            for item in ordered
        )
