"""The registro CLI shadow path must be cache-only."""

from datetime import datetime, timezone
from pathlib import Path

import treasureiq.mappa_connettore as mappa_module
from treasureiq.catalog import SnapshotStore, Surface
from treasureiq.mappa_connettore import AssetRest, AssetServizi, MappaConnettore
from treasureiq.registro_cli import _esegui_shadow

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def test_shadow_uses_existing_map_cache(monkeypatch, tmp_path: Path) -> None:
    mappa = MappaConnettore(
        codice_istat="058003",
        nome="Albano Laziale",
        sito="https://www.comune.example.it",
        sondato_il=NOW.isoformat(),
        servizi=AssetServizi(esposto=True, totale=1),
        uffici=AssetRest(esposto=True, totale=1),
        amministrazione_trasparente_via="REST",
    )
    monkeypatch.setattr(mappa_module, "_da_cache", lambda _istat: mappa)
    store = SnapshotStore(tmp_path)

    status, line = _esegui_shadow(
        "058003", store=store, measurement_id="run-1"
    )

    assert status == "shadow_ok"
    assert "shadow snapshot ok" in line
    assert store.latest_municipality("058003", Surface.ORDINARY_DATA) is not None
