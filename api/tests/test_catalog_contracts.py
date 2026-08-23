"""Contract tests for the isolated v1 catalog snapshot models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from treasureiq.catalog import (
    AccessContract,
    AccessMode,
    AgidCompatibility,
    CapabilityStatus,
    ConnectorContract,
    MunicipalityPlatformSnapshot,
    PlatformSnapshot,
    SectionStatus,
    Surface,
)

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _access() -> AccessContract:
    return AccessContract(
        transport="rest",
        endpoints=("services", "offices"),
        authentication="public",
        pagination="verified",
    )


def test_platform_snapshot_is_strict_and_immutable() -> None:
    snapshot = PlatformSnapshot(
        platform_id="wordpress_agid",
        surface=Surface.ORDINARY_DATA,
        vendor="example-vendor",
        agid_model_version="1",
        agid_compatibility=AgidCompatibility.PARTIAL,
        sections={"services": "typed"},
        access_contract=_access(),
        connector_contract=ConnectorContract(
            adapter="wordpress_agid", mode=AccessMode.DIRECT, version="1.0"
        ),
        fingerprint="sha256:platform",
        measured_at=NOW,
        measurement_id="run-1",
    )

    assert snapshot.surface is Surface.ORDINARY_DATA
    with pytest.raises(ValidationError):
        PlatformSnapshot.model_validate({**snapshot.model_dump(), "unexpected": True})


def test_municipality_snapshot_keeps_transparency_separate() -> None:
    snapshot = MunicipalityPlatformSnapshot(
        municipality_istat="058003",
        surface=Surface.TRANSPARENCY,
        platform_id="wordpress_agid",
        base_url="https://www.comune.example.it",
        platform_compatibility=AgidCompatibility.COMPATIBLE,
        municipality_adoption={"public_notices": SectionStatus.PRESENT},
        capabilities={"public_notices": CapabilityStatus.VERIFIED},
        access_mode=AccessMode.MEDIATED,
        fingerprint="sha256:municipality-at",
        measured_at=NOW,
        measurement_id="run-1",
    )

    assert snapshot.surface is Surface.TRANSPARENCY
    assert snapshot.access_mode is AccessMode.MEDIATED


def test_invalid_enum_and_istat_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MunicipalityPlatformSnapshot(
            municipality_istat="not-an-istat",
            surface="ordinary_data",
            platform_compatibility="partial",
            access_mode="unknown",
            measured_at=NOW,
            measurement_id="run-1",
        )
