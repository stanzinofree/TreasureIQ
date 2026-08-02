"""Connector interface shared by every data source.

TreasureIQ ingests from sources of wildly different quality: a clean REST API,
a CKAN catalogue, or a 2009-era HTML page. Rather than hide that difference,
the connector layer *measures* it — each connector reports how much structure
it was able to recover, and that feeds the Data Readiness Score.

A connector is responsible for fetching and normalising. It is explicitly NOT
responsible for inventing data it did not find: an unstated criterion must
stay `None` all the way to the UI. See `schema.Requirements` for why.
"""

from __future__ import annotations

import abc
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from treasureiq.schema import Opportunity

logger = logging.getLogger(__name__)

USER_AGENT = (
    "TreasureIQ/0.1 (+https://github.com/stanzinofree/TreasureIQ) "
    "civic open-data aggregator"
)


@dataclass
class FetchStats:
    """What a single ingestion run recovered.

    Feeds both operational logging and the public readiness scoring, so the
    counters must reflect reality even when that is unflattering.
    """

    source_id: str
    records_seen: int = 0
    records_emitted: int = 0
    # Structure recovered, counted per record.
    with_declared_requirements: int = 0
    with_extracted_requirements: int = 0
    with_deadline: int = 0
    with_amount: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def structured_ratio(self) -> float:
        """Share of records whose eligibility was declared, not inferred."""
        if not self.records_emitted:
            return 0.0
        return self.with_declared_requirements / self.records_emitted


class Connector(abc.ABC):
    """Base class for all ingestion connectors."""

    #: Short stable identifier, stored on every record's `Source.connector`.
    name: str

    #: Baseline trust for this transport, before per-record analysis.
    #: A REST API that serves typed fields earns more than an HTML scrape.
    transport_quality: float

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self.stats = FetchStats(source_id=self.name)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Connector:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @abc.abstractmethod
    def fetch(self) -> list[Opportunity]:
        """Fetch and normalise everything this connector can reach."""

    @staticmethod
    def hash_payload(payload: object) -> str:
        """Stable hash of a raw record, for change detection and audit."""
        import json

        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    def _get_json(self, url: str, **params: object) -> tuple[object, httpx.Headers]:
        """GET returning parsed JSON plus headers.

        Headers matter here: WordPress reports pagination in `X-WP-TotalPages`,
        and getting that wrong silently truncates a comune's catalogue — which
        would understate their readiness and misinform a citizen.
        """
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json(), resp.headers
