"""Universal acquisition seam for HTML and PDF scraping."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from treasureiq.catalog.data_contracts import DataRequest, EvidenceRef, _StrictModel


class ScrapeResult(_StrictModel):
    records: tuple[dict[str, Any], ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    retrieved_at: datetime | None = None
    requests: int = 0
    bytes: int = 0
    limitations: tuple[str, ...] = ()


class ScrapeEngine(Protocol):
    """Engine implemented by HTML/PDF fetch and extraction backends."""

    def retrieve(self, *, source_url: str, request: DataRequest) -> ScrapeResult:
        """Fetch and extract one source request without interpreting chat."""
