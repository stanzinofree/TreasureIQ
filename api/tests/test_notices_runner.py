import json
from pathlib import Path

from treasureiq.catalog.notices import NoticeSnapshot
from treasureiq.catalog.notices_runner import load_codes, run
from treasureiq.catalog.notices_store import NoticeStore


def test_runner_checkpoints_and_resumes(tmp_path: Path) -> None:
    codes = tmp_path / "codes.txt"
    codes.write_text("001001\n058003\n001001\n", encoding="utf-8")
    store = NoticeStore(tmp_path / "notices")
    checkpoint = tmp_path / "checkpoint.json"
    seen: list[str] = []

    def producer(code: str) -> NoticeSnapshot:
        seen.append(code)
        return NoticeSnapshot(source_id=code, coverage_status="coperto_senza_bandi")

    report = run(load_codes(codes), store=store, checkpoint=checkpoint, producer=producer)
    resumed = run(load_codes(codes), store=store, checkpoint=checkpoint, producer=producer)

    assert seen == ["001001", "058003"]
    assert report["coverage"] == {"coperto_senza_bandi": 2}
    assert resumed["completed"] == 2


def test_runner_queues_reachable_unhandled_source_for_review(tmp_path: Path) -> None:
    store = NoticeStore(tmp_path / "notices")
    checkpoint = tmp_path / "checkpoint.json"

    report = run(
        ["001001"],
        store=store,
        checkpoint=checkpoint,
        producer=lambda code: NoticeSnapshot(source_id=code, coverage_status="non_coperto"),
        reviewer=lambda _code: [{"label": "Bandi", "url": "https://example.test/at", "type": "concorso"}],
    )

    assert report["review"] == 1
    review = json.loads((tmp_path / "review.json").read_text("utf-8"))
    assert review["001001"]["reason"] == "rami_at_non_supportati"
