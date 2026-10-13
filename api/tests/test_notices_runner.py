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


def test_runner_queues_wordpress_without_verified_at_for_review(tmp_path: Path) -> None:
    store = NoticeStore(tmp_path / "notices")
    checkpoint = tmp_path / "checkpoint.json"

    report = run(
        ["001001"],
        store=store,
        checkpoint=checkpoint,
        producer=lambda code: NoticeSnapshot(
            source_id=code, coverage_status="wordpress_vivo_at_non_verificata"
        ),
        reviewer=lambda _code: [{"label": "Bandi", "url": "https://example.test/at", "type": "concorso"}],
    )

    assert report["coverage"] == {"wordpress_vivo_at_non_verificata": 1}
    review = json.loads((tmp_path / "review.json").read_text("utf-8"))
    assert review["001001"]["reason"] == "wordpress_vivo_at_non_verificata"


def test_runner_keeps_wordpress_without_discovered_at_in_review(tmp_path: Path) -> None:
    store = NoticeStore(tmp_path / "notices")
    checkpoint = tmp_path / "checkpoint.json"

    run(
        ["001001"],
        store=store,
        checkpoint=checkpoint,
        producer=lambda code: NoticeSnapshot(
            source_id=code, coverage_status="wordpress_vivo_at_non_verificata"
        ),
        reviewer=lambda _code: None,
    )

    review = json.loads((tmp_path / "review.json").read_text("utf-8"))
    assert review["001001"] == {
        "reason": "wordpress_vivo_at_non_verificata",
        "rami": [],
    }


def test_runner_stops_above_non_coperto_threshold_after_minimum(tmp_path: Path) -> None:
    store = NoticeStore(tmp_path / "notices")
    checkpoint = tmp_path / "checkpoint.json"
    seen: list[str] = []

    def producer(code: str) -> NoticeSnapshot:
        seen.append(code)
        status = "non_coperto" if code in {"000001", "000002"} else "coperto_senza_bandi"
        return NoticeSnapshot(source_id=code, coverage_status=status)

    report = run(
        [f"{number:06d}" for number in range(1, 13)],
        store=store,
        checkpoint=checkpoint,
        producer=producer,
        reviewer=lambda _code: [],
        min_completed=10,
        max_non_coperto_rate=0.10,
    )

    assert len(seen) == 10
    assert report["halted"] == {
        "reason": "non_coperto_rate",
        "completed": 10,
        "non_coperto": 2,
        "rate": 0.2,
    }
    assert json.loads(checkpoint.read_text("utf-8"))["halted"] == report["halted"]
