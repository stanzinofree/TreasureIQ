"""Deterministic query planning and batch selection for the chat rail."""

from __future__ import annotations

from pydantic import Field

from treasureiq.catalog.contracts import AccessMode, FreshnessStatus, Surface
from treasureiq.catalog.data_contracts import (
    DataBatch,
    DataRequest,
    DataStatus,
    Freshness,
    _StrictModel,
)


class QueryStep(_StrictModel):
    surface: Surface
    capability: str = Field(min_length=1)
    allowed_modes: tuple[AccessMode, ...] = (
        AccessMode.DIRECT,
        AccessMode.MEDIATED,
        AccessMode.INDIRECT,
    )


class QueryPlan(_StrictModel):
    request_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    steps: tuple[QueryStep, ...] = Field(min_length=1)
    fallback: AccessMode = AccessMode.UNAVAILABLE


def build_query_plan(request: DataRequest) -> QueryPlan:
    """Create the ordered fallback route for one classified data request."""
    return QueryPlan(
        request_id=request.request_id,
        source_id=request.source_id,
        steps=tuple(
            QueryStep(
                surface=request.surface,
                capability=request.capability,
                allowed_modes=(mode,),
            )
            for mode in request.allowed_modes
        ),
    )


def select_batch(plan: QueryPlan, batches: tuple[DataBatch, ...]) -> DataBatch | None:
    """Select the best result using only the plan and batch metadata.

    No language model, score, or free-text heuristic participates here.  A
    direct fresh result wins over mediated/indirect; stale results are accepted
    only when no fresh result exists.
    """
    candidates: list[tuple[int, int, int, DataBatch]] = []
    for step_index, step in enumerate(plan.steps):
        for batch in batches:
            if batch.surface is not step.surface or batch.capability != step.capability:
                continue
            if batch.status in (DataStatus.FAILED, DataStatus.UNREADABLE, DataStatus.NOT_SUPPORTED):
                continue
            try:
                mode_rank = step.allowed_modes.index(batch.access_mode)
            except ValueError:
                continue
            freshness_rank = _freshness_rank(batch.freshness)
            candidates.append((freshness_rank, step_index, mode_rank, batch))
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1], candidate[2]))
    return candidates[0][3]


def _freshness_rank(freshness: Freshness) -> int:
    return {
        FreshnessStatus.FRESH: 0,
        FreshnessStatus.LIVE: 0,
        FreshnessStatus.UNKNOWN: 1,
        FreshnessStatus.STALE: 2,
        FreshnessStatus.INVALID: 3,
    }[freshness.status]
