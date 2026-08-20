"""Runtime registry for expandable catalog adapters."""

from __future__ import annotations

from treasureiq.catalog.adapters.base import CatalogAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, CatalogAdapter] = {}

    def register(self, adapter: CatalogAdapter) -> None:
        if adapter.name in self._adapters:
            raise ValueError(f"adapter already registered: {adapter.name}")
        self._adapters[adapter.name] = adapter

    def resolve(self, *, platform_id: str, surface: str) -> CatalogAdapter | None:
        for adapter in self._adapters.values():
            if adapter.supports(platform_id, surface):
                return adapter
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(self._adapters)
