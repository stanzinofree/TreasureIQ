"""Deterministic query planning and batch selection for the chat rail."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from treasureiq.catalog.contracts import (
    CAPABILITY_NOTICES,
    CAPABILITY_SERVICES,
    AccessMode,
    FreshnessStatus,
    Surface,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.catalog.data_contracts import (
    DataBatch,
    DataRequest,
    DataStatus,
    Freshness,
    FreshnessPolicy,
    _StrictModel,
)

if TYPE_CHECKING:
    from treasureiq.chat.intent import ChatRecognitionContract


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


_CAPABILITY_BY_TOPIC = {
    "anagrafe_carta_identita": "offices",
    "accesso_atti": "offices",
    "tributi": "services",
    "bandi": CAPABILITY_NOTICES,
}


def request_from_recognition(
    recognition: "ChatRecognitionContract",
    *,
    source_id: str,
    capability_override: str | None = None,
    surface_override: Surface | None = None,
) -> DataRequest:
    """Translate the closed chat contract into a deterministic data request.

    No model call or source selection happens here. Connector availability is
    evaluated later by ``build_query_plan`` and ``select_batch``.
    """

    topic = recognition.intent.topic.value
    kind = recognition.intent.kind.value
    surface = surface_override or (
        Surface.TRANSPARENCY if topic == "bandi" else Surface.ORDINARY_DATA
    )
    capability = capability_override or _CAPABILITY_BY_TOPIC.get(
        topic, "opportunities" if kind == "agevolazione" else "services"
    )
    return DataRequest(
        request_id=f"chat:{source_id}:{surface.value}:{capability}",
        source_id=source_id,
        surface=surface,
        capability=capability,
        selection={"topic": topic, "kind": kind},
        filters={"keys": list(recognition.filter_keys)},
        freshness=FreshnessPolicy(max_age_seconds=86400),
        manifest_revision=1,
    )


def service_portal_request(
    *,
    source_id: str,
    service_id: str,
    capability: str = "authenticated_service",
    freshness: FreshnessPolicy | None = None,
) -> DataRequest:
    """Build the deterministic request for a previously discovered service.

    ``service_id`` must come from a ``ServiceReference`` selected by the
    recognition layer.  Free text and authentication details never enter this
    constructor.
    """

    return DataRequest(
        request_id=f"chat:{source_id}:{Surface.SERVICE_PORTAL.value}:{service_id}",
        source_id=source_id,
        surface=Surface.SERVICE_PORTAL,
        capability=capability,
        selection={"service_id": service_id},
        freshness=freshness or FreshnessPolicy(max_age_seconds=86400),
        manifest_revision=1,
    )


def service_request(
    *,
    source_id: str,
    service_key: ServiceKey,
    freshness: FreshnessPolicy | None = None,
) -> DataRequest:
    """Build the deterministic request for a recognised civic service (Ramo 3).

    ``service_key`` is a ``ServiceKey`` enum value, never free text: the type
    itself guarantees no caller can synthesise a service capability from an
    arbitrary string (same provenance discipline as ``service_portal_request``,
    which keys on a confirmed entrypoint URL).  The request lands on the
    ORDINARY_DATA surface with the shared ``CAPABILITY_SERVICES`` — distinct
    from the SERVICE_PORTAL/INDIRECT authenticated sub-case (D-R3-2), which
    keeps its own ``service_portal_request``.

    No cache lookup or connector call happens here; this is only the request
    contract.  Availability is evaluated later by ``build_query_plan`` /
    ``select_batch``.
    """

    return DataRequest(
        request_id=f"chat:{source_id}:{Surface.ORDINARY_DATA.value}:{service_key.value}",
        source_id=source_id,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection={"service_key": service_key.value},
        freshness=freshness or FreshnessPolicy(max_age_seconds=86400),
        manifest_revision=1,
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
