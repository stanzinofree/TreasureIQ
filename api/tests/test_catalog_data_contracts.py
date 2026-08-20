"""Contracts for the adapter-to-chat data boundary."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from treasureiq.catalog import (
    AccessMode,
    ConnectorRef,
    DataBatch,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
    FreshnessPolicy,
    RequestLimits,
    Surface,
    TransportMeta,
)

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _request() -> DataRequest:
    return DataRequest(
        request_id="request-1",
        source_id="comune-058003",
        surface=Surface.ORDINARY_DATA,
        capability="services",
        selection={"topic": "mensa_scolastica"},
        freshness=FreshnessPolicy(max_age_seconds=604800),
        limits=RequestLimits(max_records=20),
        manifest_revision=12,
    )


def test_data_batch_preserves_capability_access_mode() -> None:
    batch = DataBatch(
        request_id="request-1",
        status=DataStatus.FULFILLED,
        access_mode=AccessMode.MEDIATED,
        source_id="comune-058003",
        surface=Surface.ORDINARY_DATA,
        capability="services",
        records=({"canonical_id": "service:1"},),
        evidence=(EvidenceRef(evidence_id="e-1", field="title"),),
        freshness=Freshness(status="live", retrieved_at=NOW),
        transport=TransportMeta(requests=2, bytes=1200),
        connector=ConnectorRef(name="wordpress_agid", version="1.0"),
    )

    assert batch.access_mode is AccessMode.MEDIATED
    assert batch.records[0]["canonical_id"] == "service:1"


def test_request_and_batch_are_strict() -> None:
    request = _request()
    with pytest.raises(ValidationError):
        DataRequest.model_validate({**request.model_dump(), "unexpected": True})

    with pytest.raises(ValidationError):
        DataBatch(
            request_id="request-1",
            status="fulfilled",
            access_mode="unknown",
            source_id="comune-058003",
            surface="ordinary_data",
            capability="services",
            freshness={"status": "live"},
            connector={"name": "x", "version": "1"},
        )
