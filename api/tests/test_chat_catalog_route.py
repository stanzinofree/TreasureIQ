from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessMode,
    AgidCompatibility,
    MunicipalityPlatformSnapshot,
    SnapshotStore,
    Surface,
)
from treasureiq.chat import respond


def _snapshot(mode: AccessMode) -> MunicipalityPlatformSnapshot:
    return MunicipalityPlatformSnapshot(
        municipality_istat="058003",
        surface=Surface.ORDINARY_DATA,
        platform_id="wp_design_comuni",
        platform_compatibility=AgidCompatibility.PARTIAL,
        access_mode=mode,
        measured_at=datetime.now(timezone.utc),
        measurement_id="sweep-1",
    )


def test_chat_reads_catalog_route_when_imported(monkeypatch, tmp_path) -> None:
    store = SnapshotStore(tmp_path / "catalog")
    store.save_municipality(_snapshot(AccessMode.MEDIATED))
    monkeypatch.setattr(respond, "DATA_DIR", tmp_path)

    assert respond._catalog_access_mode("058003") is AccessMode.MEDIATED


def test_chat_keeps_legacy_fallback_without_snapshot(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(respond, "DATA_DIR", tmp_path)

    assert respond._catalog_access_mode("058003") is None
