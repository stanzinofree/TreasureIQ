from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessMode,
    ConnectorRef,
    DataBatch,
    DataRequest,
    DataStatus,
    Freshness,
    FreshnessPolicy,
    FreshnessStatus,
    QueryStep,
    RequestLimits,
    Surface,
    build_query_plan,
    select_batch,
)


def _request() -> DataRequest:
    return DataRequest(
        request_id="req-1",
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        capability="offices",
        freshness=FreshnessPolicy(max_age_seconds=3600),
        limits=RequestLimits(),
        manifest_revision=1,
    )


def _batch(mode: AccessMode, status: FreshnessStatus) -> DataBatch:
    return DataBatch(
        request_id="req-1",
        status=DataStatus.FULFILLED,
        access_mode=mode,
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        capability="offices",
        records=({"nome": "Anagrafe"},),
        freshness=Freshness(
            status=status,
            retrieved_at=datetime.now(timezone.utc),
        ),
        connector=ConnectorRef(name="wordpress_agid", version="1"),
    )


def test_plan_is_closed_to_one_surface_and_capability() -> None:
    plan = build_query_plan(_request())

    assert plan.steps == (QueryStep(surface=Surface.ORDINARY_DATA, capability="offices"),)
    assert plan.fallback is AccessMode.UNAVAILABLE


def test_direct_fresh_batch_wins_over_mediated_batch() -> None:
    plan = build_query_plan(_request())
    selected = select_batch(
        plan,
        (
            _batch(AccessMode.MEDIATED, FreshnessStatus.FRESH),
            _batch(AccessMode.DIRECT, FreshnessStatus.FRESH),
        ),
    )

    assert selected is not None
    assert selected.access_mode is AccessMode.DIRECT


def test_stale_batch_is_last_resort() -> None:
    plan = build_query_plan(_request())
    selected = select_batch(
        plan,
        (
            _batch(AccessMode.DIRECT, FreshnessStatus.STALE),
            _batch(AccessMode.MEDIATED, FreshnessStatus.FRESH),
        ),
    )

    assert selected is not None
    assert selected.access_mode is AccessMode.MEDIATED
