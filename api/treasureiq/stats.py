"""Cross-comune aggregation for the `/api/stats`, `/api/status` and
`/api/comune-nearby` endpoints.

Kept out of `api.py` for the same reason `readiness.py` is: these are number-
crunching functions over already-loaded evidence, not route handlers. Routes
stay thin mappers from these dataclasses to the flat `*Out` response models.

Nothing here makes a network call to a municipal site. `/api/status` in
particular is deliberately answered from what ingestion already wrote to
disk (D-16 instrumentation, seed snapshots) rather than by probing the
comune's server on every page load — see `build_system_status`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from treasureiq.readiness import score_comune
from treasureiq.schema import Opportunity

#: TreasureIQ's own application version. Deliberately distinct from
#: `treasureiq.schema.SPEC_VERSION` (the version of the *data* shape on
#: disk): one tracks what this codebase can do today, the other what shape a
#: record was written in. They will drift from each other independently and
#: must never be conflated in a response.
APP_VERSION = "0.2.0"


@dataclass
class AppStats:
    """The `/api/stats` payload, aggregated across every configured comune."""

    app_version: str
    comuni_measured: int
    records_total: int
    requirements_verified: int
    avg_recovery_seconds: float | None
    sources_below_full_openness_pct: float | None


@dataclass
class SourceStatus:
    """One comune's row in `/api/status`.

    `reachable` is `None` when it was not (and could not honestly be)
    checked — never a guessed `True`.
    """

    codice_istat: str
    nome: str
    reachable: bool | None
    last_ingested: datetime | None
    records: int


@dataclass
class SystemStatus:
    overall: str  # "ok" | "degraded" | "down"
    sources: list[SourceStatus] = field(default_factory=list)


@dataclass
class Centroid:
    codice_istat: str
    nome: str
    lat: float
    lon: float


#: Town-centre coordinates for the comuni this demo ships seed data for.
#: Sourced from comuni-italiani.it's per-comune geographic data page (ISTAT-
#: derived), fetched 2026-08-03:
#:   - Albano Laziale (058003): https://www.comuni-italiani.it/058/003/clima.html
#:     -> 41.727 N, 12.6322 E
#:   - Fonte Nuova (058122):    https://www.comuni-italiani.it/058/122/clima.html
#:     -> 42.0018 N, 12.6221 E
#: Not guessed: a wrong centroid here would misresolve a citizen's device to
#: the wrong comune, which is the one thing D-15 (comune, not consulting
#: engine, decides eligibility) exists to prevent upstream of it.
CENTROIDS: list[Centroid] = [
    Centroid(codice_istat="058003", nome="Albano Laziale", lat=41.727, lon=12.6322),
    Centroid(codice_istat="058122", nome="Fonte Nuova", lat=42.0018, lon=12.6221),
]

#: A device several kilometres from a comune's centre is not "in" it. Chosen
#: to comfortably cover each comune's own territory (both centroids sit
#: roughly 20-24 km^2, i.e. a few km across) without reaching the other
#: comune (Albano <-> Fonte Nuova are ~30 km apart), so the two never
#: compete for the same coordinate.
MAX_NEARBY_RADIUS_KM = 10.0

_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest_comune(*, lat: float, lon: float) -> Centroid | None:
    """Resolve a device coordinate to the nearest supported comune, if close enough.

    This answers "which comune is this device physically near right now" —
    it must never be read as, or wired into, a claim about where the citizen
    is *resident* (R-9: we do not invent facts about the citizen). The
    caller is responsible for keeping that distinction explicit in the
    response shape; see `api.py`'s `/api/comune-nearby`.
    """
    best: Centroid | None = None
    best_distance = math.inf
    for centroid in CENTROIDS:
        distance = _haversine_km(lat, lon, centroid.lat, centroid.lon)
        if distance < best_distance:
            best, best_distance = centroid, distance
    if best is None or best_distance > MAX_NEARBY_RADIUS_KM:
        return None
    return best


def _count_verified_requirements(records: list[Opportunity]) -> int:
    """Requirements whose declared quote survived the D-05 quote gate.

    `requirements_recovered` (D-16) is written by the pages connector only
    after `ExtractionResult.to_requirements` (`extract/llm.py`) has checked
    every declared quote against the source text; a field whose quote could
    not be found, or fell outside the truncated corpus, is dropped before
    this count is taken — so summing it can never count an invented or
    unconfirmed claim. `None` (typed `servizi` records, which carry no LLM
    quote gate at all, or pages ingested before this instrumentation
    existed) is treated as zero verified requirements, not as a missing
    measurement: a record nobody ran extraction on legitimately contributed
    none.
    """
    return sum(r.requirements_recovered or 0 for r in records)


def compute_app_stats(
    *,
    comuni: dict[str, dict],
    records_by_comune: dict[str, list[Opportunity]],
) -> AppStats:
    """Aggregate the headline numbers across every configured comune.

    `comuni` is the API's `COMUNI` registry (nome/seed/datasets_on_dati_gov
    metadata); `records_by_comune` holds whatever the caller already loaded
    for each codice ISTAT. This function reads no file itself, so it stays
    trivially testable against fixtures.
    """
    all_records = [r for records in records_by_comune.values() for r in records]

    measured_seconds = [
        float(r.extraction_seconds)
        for r in all_records
        if r.extraction_seconds is not None
    ]
    avg_recovery_seconds = (
        sum(measured_seconds) / len(measured_seconds) if measured_seconds else None
    )

    # "Measured" means ingestion actually produced records for the comune —
    # an empty or absent snapshot has no readiness score to compare against.
    measured_comuni = [
        istat for istat, records in records_by_comune.items() if records
    ]
    below_full = 0
    for istat in measured_comuni:
        meta = comuni[istat]
        report = score_comune(
            ente=meta["ente"],
            codice_istat=istat,
            records=records_by_comune[istat],
            datasets_on_dati_gov=meta.get("datasets_on_dati_gov", 0),
        )
        if report.score < 100:
            below_full += 1
    sources_below_full_openness_pct = (
        round(100 * below_full / len(measured_comuni), 1)
        if measured_comuni
        else None
    )

    return AppStats(
        app_version=APP_VERSION,
        comuni_measured=len(measured_comuni),
        records_total=len(all_records),
        requirements_verified=_count_verified_requirements(all_records),
        avg_recovery_seconds=avg_recovery_seconds,
        sources_below_full_openness_pct=sources_below_full_openness_pct,
    )


def build_system_status(
    *,
    comuni: dict[str, dict],
    seed_dir: Path,
) -> SystemStatus:
    """Derive `/api/status` from the committed seed snapshots, not a live probe.

    Hitting each comune's real WordPress site on every dashboard load would
    make a user-facing page's latency and uptime depend on a public
    administration's server, and would send it unasked-for traffic on every
    visitor. Everything here therefore comes from what ingestion already
    wrote: does the seed file exist, how many records does it hold, and what
    is the most recent `source.fetched_at` among them. `reachable` is left
    `None` throughout — "not checked" — because a value this route cannot
    honestly produce must not be invented as `True`.
    """
    sources: list[SourceStatus] = []
    for istat, meta in comuni.items():
        path = seed_dir / meta["seed"]
        if not path.exists():
            sources.append(
                SourceStatus(
                    codice_istat=istat,
                    nome=meta["nome"],
                    reachable=None,
                    last_ingested=None,
                    records=0,
                )
            )
            continue

        raw = json.loads(path.read_text("utf-8"))
        records = [Opportunity.model_validate(item) for item in raw]
        fetched_ats = [r.source.fetched_at for r in records]
        last_ingested = max(fetched_ats) if fetched_ats else None
        sources.append(
            SourceStatus(
                codice_istat=istat,
                nome=meta["nome"],
                reachable=None,
                last_ingested=last_ingested,
                records=len(records),
            )
        )

    if not sources:
        overall = "down"
    elif all(s.records > 0 for s in sources):
        overall = "ok"
    elif any(s.records > 0 for s in sources):
        overall = "degraded"
    else:
        overall = "down"

    return SystemStatus(overall=overall, sources=sources)
