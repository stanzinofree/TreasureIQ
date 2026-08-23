from datetime import datetime, timezone

from treasureiq.catalog import SnapshotStore, Surface
from treasureiq.catalog.sweep_bridge import snapshots_from_sweep_row
from treasureiq.catalog.sweep_import import persist_sweep_snapshots


def test_sweep_import_persists_both_surfaces(monkeypatch, tmp_path) -> None:
    snapshots = snapshots_from_sweep_row(
        {
            "codice_istat": "058003",
            "piattaforma": "wp_design_comuni",
            "piattaforma_at": "jcitygov",
            "indirizzabilita": "api_uffici",
            "aderenza": 50,
        },
        measurement_id="sweep-1",
        measured_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "treasureiq.catalog.sweep_bridge.snapshots_from_sweep_db",
        lambda *args, **kwargs: snapshots,
    )
    # The importer imports the function into its module at import time.
    monkeypatch.setattr(
        "treasureiq.catalog.sweep_import.snapshots_from_sweep_db",
        lambda *args, **kwargs: snapshots,
    )

    paths = persist_sweep_snapshots(
        tmp_path / "storico.db",
        store=SnapshotStore(tmp_path / "catalog"),
        codice_istat="058003",
        measurement_id="sweep-1",
        measured_at=datetime.now(timezone.utc),
    )

    assert len(paths) == 2
    assert SnapshotStore(tmp_path / "catalog").latest_municipality(
        "058003", Surface.TRANSPARENCY
    ) is not None
