"""Acquisition contract shared by REST, platform and scraping connectors.

Connectors retrieve and normalize source material. They do not choose a chat
answer; that remains the responsibility of the deterministic query planner.
Adapters can then project this result into the public catalog ``DataBatch``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from treasureiq.catalog.contracts import AccessMode
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
    TransportMeta,
    _StrictModel,
)
from treasureiq.catalog.service_contracts import ServiceReference
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore


class ConnectorResult(_StrictModel):
    """The closed result of one connector acquisition attempt."""

    request_id: str
    source_id: str
    status: DataStatus
    access_mode: AccessMode
    records: tuple[dict[str, Any], ...] = ()
    service_references: tuple[ServiceReference, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    freshness: Freshness
    limitations: tuple[str, ...] = ()
    transport: TransportMeta = TransportMeta()
    connector: ConnectorRef
    retrieved_at: datetime | None = None


class SourceConnector(Protocol):
    """Acquisition seam implemented by every source connector."""

    name: str
    version: str

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        """Return whether this connector can attempt this source request."""

    def retrieve(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> ConnectorResult:
        """Acquire source records without interpreting the user's language."""
