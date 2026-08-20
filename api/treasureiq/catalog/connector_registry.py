"""Runtime registry for source acquisition connectors."""

from __future__ import annotations

from treasureiq.catalog.connectors import SourceConnector
from treasureiq.catalog.data_contracts import DataRequest


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, SourceConnector] = {}

    def register(self, connector: SourceConnector) -> None:
        if connector.name in self._connectors:
            raise ValueError(f"connector already registered: {connector.name}")
        self._connectors[connector.name] = connector

    def resolve(self, *, request: DataRequest, platform_id: str) -> SourceConnector | None:
        for connector in self._connectors.values():
            if connector.supports(request, platform_id=platform_id):
                return connector
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(self._connectors)
