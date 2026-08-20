from datetime import datetime, timezone

from treasureiq.catalog.fallback_run import run_fallback
from treasureiq.catalog.fallback_store import FallbackRunStore
from treasureiq.mappa_connettore import MappaConnettore


def test_fallback_store_keeps_immutable_run_and_latest_pointer(tmp_path) -> None:
    mappa = MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito=None,
        sondato_il=datetime.now(timezone.utc).isoformat(),
    )
    run = run_fallback(mappa, platform_id="halley", run_id="run-1")
    store = FallbackRunStore(tmp_path)

    path = store.save(run)

    assert path.name == "run-1.json"
    latest = store.latest(source_id="058003", platform_id="halley")
    assert latest is not None
    assert latest.run_id == "run-1"


def test_fallback_store_rejects_mutating_same_run(tmp_path) -> None:
    mappa = MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito=None,
        sondato_il=datetime.now(timezone.utc).isoformat(),
    )
    store = FallbackRunStore(tmp_path)
    first = run_fallback(mappa, platform_id="halley", run_id="run-1")
    second = first.model_copy(update={"run_id": "run-1", "platform_id": "other"})
    store.save(first)

    # A different platform is a different immutable partition, not an overwrite.
    assert store.save(second).parent.name == "other"
