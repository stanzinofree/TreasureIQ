from datetime import datetime, timezone
from pathlib import Path

from treasureiq.bandi_live import BandiLiveEsito
from treasureiq.catalog import notices_store
from treasureiq.catalog.notices import NoticeSnapshot
from treasureiq.catalog.notices_store import NoticeStore


def _snapshot(*, retrieved_at: str | None = None) -> NoticeSnapshot:
    return NoticeSnapshot(
        source_id="058003",
        comune_nome="Albano Laziale",
        coverage_status="coperto_senza_bandi",
        retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(),
    )


def test_store_roundtrip_including_empty_coverage(tmp_path: Path) -> None:
    store = NoticeStore(tmp_path)
    snapshot = _snapshot()

    path = store.save(snapshot)

    assert path == tmp_path / "058003.json"
    assert store.load("058003") == snapshot


def test_store_ignores_corrupt_or_stale_snapshot(tmp_path: Path) -> None:
    store = NoticeStore(tmp_path)
    path = store.path_for("058003")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    assert store.load("058003") is None

    store.save(_snapshot(retrieved_at="2020-01-01T00:00:00+00:00"))
    assert store.load("058003", max_age_seconds=60) is None


def test_produce_persists_non_covered_result_without_network(tmp_path: Path, monkeypatch) -> None:
    def fake_bandi(codice_istat: str, *, usa_cache: bool) -> BandiLiveEsito:
        assert codice_istat == "058003"
        assert usa_cache is True
        return BandiLiveEsito(
            codice_istat=codice_istat,
            comune_nome="Albano Laziale",
            esito="non_coperto",
            gradino=None,
            verificato_il=datetime.now(timezone.utc).isoformat(),
        )

    monkeypatch.setattr(notices_store, "bandi_arricchiti", fake_bandi)
    store = NoticeStore(tmp_path)

    snapshot = notices_store.produce("058003", store=store)

    assert snapshot.coverage_status == "non_coperto"
    assert store.load("058003") == snapshot
