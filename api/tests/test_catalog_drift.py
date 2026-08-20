"""Pure drift classification tests."""

from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessContract,
    AccessMode,
    AgidCompatibility,
    ConnectorContract,
    DriftKind,
    PlatformSnapshot,
    Surface,
    compare_snapshots,
)

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _snapshot(*, measurement: str, endpoint: str = "services", mode: AccessMode = AccessMode.DIRECT):
    return PlatformSnapshot(
        platform_id="wordpress_agid",
        surface=Surface.ORDINARY_DATA,
        agid_model_version="1",
        agid_compatibility=AgidCompatibility.PARTIAL,
        sections={"services": "typed"},
        access_contract=AccessContract(
            transport="rest",
            endpoints=(endpoint,),
            authentication="public",
            schema_version="wp-v1",
        ),
        connector_contract=ConnectorContract(
            adapter="wordpress_agid", mode=mode, version="1.0"
        ),
        fingerprint=f"sha256:{endpoint}:{mode.value}",
        measured_at=NOW,
        measurement_id=measurement,
    )


def test_same_snapshot_is_unchanged() -> None:
    event = compare_snapshots(_snapshot(measurement="run-1"), _snapshot(measurement="run-2"))
    assert event.kind is DriftKind.UNCHANGED
    assert event.changes == ()


def test_endpoint_change_has_priority_over_fingerprint_only() -> None:
    event = compare_snapshots(
        _snapshot(measurement="run-1"),
        _snapshot(measurement="run-2", endpoint="offices"),
    )
    assert event.kind is DriftKind.ENDPOINT_CHANGED
    assert "endpoints" in event.changes


def test_access_mode_degradation_is_explicit() -> None:
    event = compare_snapshots(
        _snapshot(measurement="run-1", mode=AccessMode.DIRECT),
        _snapshot(measurement="run-2", mode=AccessMode.MEDIATED),
    )
    assert event.kind is DriftKind.CONNECTOR_DEGRADED
    assert "connector_mode" in event.changes
