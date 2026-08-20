from datetime import datetime, timezone

from treasureiq.catalog.fallback_run import run_fallback
from treasureiq.mappa_connettore import MappaConnettore


def test_backoffice_fallback_run_is_auditable_without_chat(monkeypatch) -> None:
    mappa = MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito=None,
        sondato_il=datetime.now(timezone.utc).isoformat(),
    )

    result = run_fallback(mappa, platform_id="halley", run_id="run-test")

    assert result.run_id == "run-test"
    assert result.source_id == "058003"
    assert len(result.batches) == 4
    assert all(batch.access_mode.value == "indirect" for batch in result.batches)
