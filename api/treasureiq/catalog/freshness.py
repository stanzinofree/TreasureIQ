"""Shared temporal freshness policy for the catalog layer.

One place computes "how old is this read, and is it still fresh?" so every
store and projection agrees on the same rule.  It reads only a timestamp and a
max-age, returns a ``Freshness``, and never touches the network or a platform:
offices (``flotta/_projection``), notices (``notices``) and the resolved-service
cache (``service_cache``) all import from here instead of each re-implementing
the age math.

Naive timestamps are assumed UTC (normalised before the age subtraction) so a
timezone-less ISO string can never produce a negative or exploding age.
"""

from __future__ import annotations

from datetime import datetime, timezone

from treasureiq.catalog.contracts import FreshnessStatus
from treasureiq.catalog.data_contracts import Freshness


def freshness_da_datetime(retrieved_at: datetime, max_age_seconds: int) -> Freshness:
    """Freshness from an already-parsed datetime (naive assumed UTC)."""
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    age = max(0, int((datetime.now(timezone.utc) - retrieved_at).total_seconds()))
    status = FreshnessStatus.FRESH if age <= max_age_seconds else FreshnessStatus.STALE
    return Freshness(status=status, retrieved_at=retrieved_at, source_age_seconds=age)


def freshness(measured_at: str | None, max_age_seconds: int) -> Freshness:
    """Freshness from an ISO timestamp string.

    ``None`` → UNKNOWN (the source never reported when it was read); an
    unparseable string → INVALID; otherwise the age-based FRESH/STALE verdict.
    """
    if measured_at is None:
        return Freshness(status=FreshnessStatus.UNKNOWN)
    try:
        retrieved_at = datetime.fromisoformat(measured_at)
    except (TypeError, ValueError):
        return Freshness(status=FreshnessStatus.INVALID)
    return freshness_da_datetime(retrieved_at, max_age_seconds)
