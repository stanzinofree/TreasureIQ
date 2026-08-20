"""Shadow-run orchestration tests."""

from datetime import datetime, timezone
from pathlib import Path

from treasureiq.catalog import SnapshotStore, Surface, persist_shadow_snapshots
from treasureiq.mappa_connettore import AssetRest, AssetServizi, MappaConnettore

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _mappa(at: str = "REST") -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Albano Laziale",
        sito="https://www.comune.example.it",
        sondato_il=NOW.isoformat(),
        servizi=AssetServizi(esposto=True, rest_base="servizi", totale=2),
        uffici=AssetRest(esposto=True, rest_base="uffici", totale=1),
        amministrazione_trasparente_via=at,
    )


def test_shadow_run_persists_four_snapshots_and_then_reports_drift(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    assert persist_shadow_snapshots(
        _mappa(), store=store, measurement_id="run-1", measured_at=NOW
    ) == ()

    events = persist_shadow_snapshots(
        _mappa(at="scrape"), store=store, measurement_id="run-2", measured_at=NOW
    )

    assert len(events) == 4
    assert any(event.surface == "transparency" for event in events)
    assert store.latest_municipality("058003", Surface.TRANSPARENCY) is not None
