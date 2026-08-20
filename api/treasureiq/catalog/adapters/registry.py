"""Runtime registry for expandable catalog adapters."""

from __future__ import annotations

from treasureiq.catalog.adapters.base import CatalogAdapter
from treasureiq.catalog.contracts import AccessMode
from treasureiq.catalog.data_contracts import DataRequest, FreshnessPolicy, RequestLimits
from treasureiq.catalog.plugins import PluginManifest


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, CatalogAdapter] = {}

    def register(self, adapter: CatalogAdapter) -> None:
        if adapter.name in self._adapters:
            raise ValueError(f"adapter already registered: {adapter.name}")
        self._adapters[adapter.name] = adapter

    def resolve(
        self,
        *,
        platform_id: str,
        surface: str,
        capability: str | None = None,
        access_mode: AccessMode | None = None,
    ) -> CatalogAdapter | None:
        for adapter in self._adapters.values():
            if not adapter.manifest.supports_platform(platform_id):
                continue
            if adapter.manifest.supports(surface=surface, capability=capability):
                if access_mode is not None and not any(
                    item.surface.value == surface
                    and (capability is None or item.capability == capability)
                    and access_mode in item.allowed_modes
                    for item in adapter.manifest.capabilities
                ):
                    continue
                return adapter
        return None

    def manifest(self, platform_id: str) -> PluginManifest | None:
        adapter = self._adapters.get(platform_id)
        return adapter.manifest if adapter is not None else None

    def requests_for(
        self,
        *,
        source_id: str,
        platform_id: str,
        request_prefix: str,
        freshness: FreshnessPolicy,
        limits: RequestLimits,
        manifest_revision: int,
    ) -> tuple[DataRequest, ...]:
        manifest = self.manifest(platform_id)
        if manifest is None:
            return ()
        return manifest.requests(
            source_id=source_id,
            request_prefix=request_prefix,
            freshness=freshness,
            limits=limits,
            manifest_revision=manifest_revision,
        )

    def fallback_requests_for(
        self,
        *,
        source_id: str,
        platform_id: str,
        request_prefix: str,
        freshness: FreshnessPolicy,
        limits: RequestLimits,
        manifest_revision: int,
    ) -> tuple[DataRequest, ...]:
        """Build requests from the first wildcard manifest for this source.

        Native manifests always win in ``requests_for``. This explicit method
        is the only way to ask for an indirect fallback, keeping ordinary chat
        projection from triggering scraping as a side effect.
        """
        for adapter in self._adapters.values():
            manifest = adapter.manifest
            if manifest.plugin_id == platform_id or not manifest.supports_platform(platform_id):
                continue
            return manifest.requests(
                source_id=source_id,
                request_prefix=request_prefix,
                freshness=freshness,
                limits=limits,
                manifest_revision=manifest_revision,
            )
        return ()

    def names(self) -> tuple[str, ...]:
        return tuple(self._adapters)
