"""Filesystem persistence tests for the shadow catalog."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from treasureiq.catalog import (
    AccessContract,
    AgidCompatibility,
    PlatformSnapshot,
    SectionStatus,
    SnapshotStore,
    Surface,
    municipality_snapshots,
)
from treasureiq.mappa_connettore import AssetRest, AssetServizi, MappaConnettore

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _ordinary() -> PlatformSnapshot:
    return PlatformSnapshot(
        platform_id="wordpress_agid",
        surface=Surface.ORDINARY_DATA,
        agid_compatibility=AgidCompatibility.PARTIAL,
        access_contract=AccessContract(
            transport="rest", authentication="public"
        ),
        fingerprint="sha256:one",
        measured_at=NOW,
        measurement_id="run-1",
    )


def _mappa() -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Albano Laziale",
        sito="https://www.comune.example.it",
        sondato_il=NOW.isoformat(),
        servizi=AssetServizi(esposto=True, totale=1),
        uffici=AssetRest(esposto=True, totale=1),
        amministrazione_trasparente_via="REST",
    )


def test_store_keeps_measurement_and_reads_latest(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    snapshot = _ordinary()

    stored = store.save_platform(snapshot)

    assert stored.exists()
    assert store.latest_platform("wordpress_agid", Surface.ORDINARY_DATA) == snapshot
    assert (tmp_path / "platform" / "wordpress_agid" / "ordinary_data" / "latest.json").exists()


def test_store_rejects_different_content_for_same_measurement(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    store.save_platform(_ordinary())
    changed = _ordinary().model_copy(update={"fingerprint": "sha256:two"})

    with pytest.raises(ValueError, match="contenuto diverso"):
        store.save_platform(changed)


def test_store_keeps_ordinary_and_transparency_separate(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    ordinary, transparency = municipality_snapshots(
        _mappa(), measurement_id="run-1", measured_at=NOW
    )

    store.save_municipality(ordinary)
    store.save_municipality(transparency)

    assert (
        store.latest_municipality("058003", Surface.ORDINARY_DATA)
        == ordinary
    )
    assert (
        store.latest_municipality("058003", Surface.TRANSPARENCY)
        == transparency
    )
    assert ordinary.municipality_adoption["services"] is SectionStatus.PRESENT
