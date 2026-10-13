"""Resumable, single-threaded national notices discovery runner."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Callable

from treasureiq.catalog.notices import NoticeSnapshot
from treasureiq.catalog.notices_store import NoticeStore, produce
from treasureiq.frame_manifest import write_atomic


def load_codes(path: Path) -> list[str]:
    """One ISTAT code per line; preserve order and discard duplicate blanks."""
    seen: set[str] = set()
    return [
        code for code in (line.strip() for line in path.read_text("utf-8").splitlines())
        if code and not (code in seen or seen.add(code))
    ]


def run(
    codes: list[str], *, store: NoticeStore, checkpoint: Path, delay_seconds: float = 0.0,
    producer: Callable[[str], NoticeSnapshot] | None = None,
    reviewer: Callable[[str], list[dict[str, str]] | None] | None = None,
    min_completed: int = 0,
    max_non_coperto_rate: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Persist each outcome and checkpoint after every municipality."""
    try:
        state = json.loads(checkpoint.read_text("utf-8")) if checkpoint.exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    completed = set(state.get("completed") or [])
    errors = dict(state.get("errors") or {})
    halted = state.get("halted")
    review_path = checkpoint.with_name("review.json")
    try:
        reviews = json.loads(review_path.read_text("utf-8")) if review_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        reviews = {}
    discover = producer or (lambda code: produce(code, store=store))
    inspect = reviewer or _review_candidate

    def report() -> dict[str, object]:
        statuses = Counter()
        for code in completed:
            snapshot = store.load(code)
            if snapshot is not None:
                statuses[snapshot.coverage_status] += 1
        return {
            "completed": len(completed),
            "errors": errors,
            "coverage": dict(statuses),
            "review": len(reviews),
            "halted": halted,
        }

    if halted:
        return report()

    for code in codes:
        if code in completed:
            continue
        try:
            snapshot = discover(code)
            store.save(snapshot)
            completed.add(code)
            errors.pop(code, None)
            if snapshot.coverage_status == "wordpress_vivo_at_non_verificata":
                reviews[code] = {
                    "reason": "wordpress_vivo_at_non_verificata",
                    "rami": inspect(code) or [],
                }
            elif snapshot.coverage_status == "non_coperto":
                rami = inspect(code)
                if rami:
                    reviews[code] = {"reason": "rami_at_non_supportati", "rami": rami}
        except Exception as exc:  # an individual portal cannot stop the national run
            errors[code] = type(exc).__name__
        write_atomic(
            checkpoint,
            json.dumps(
                {"completed": sorted(completed), "errors": errors, "halted": halted},
                ensure_ascii=False,
                indent=1,
            ) + "\n",
        )
        write_atomic(review_path, json.dumps(reviews, ensure_ascii=False, indent=1) + "\n")
        non_coperti = sum(
            snapshot.coverage_status == "non_coperto"
            for comune in completed
            if (snapshot := store.load(comune)) is not None
        )
        if (
            max_non_coperto_rate is not None
            and len(completed) >= min_completed
            and non_coperti / len(completed) > max_non_coperto_rate
        ):
            halted = {
                "reason": "non_coperto_rate",
                "completed": len(completed),
                "non_coperto": non_coperti,
                "rate": non_coperti / len(completed),
            }
            write_atomic(
                checkpoint,
                json.dumps(
                    {"completed": sorted(completed), "errors": errors, "halted": halted},
                    ensure_ascii=False,
                    indent=1,
                ) + "\n",
            )
            break
        if delay_seconds:
            sleep(delay_seconds)

    return report()


def _review_candidate(code: str) -> list[dict[str, str]] | None:
    from treasureiq.alberatura import scopri_rami

    rami = scopri_rami(code)
    if not rami:
        return None
    return [{"label": ramo.etichetta, "url": ramo.url, "type": ramo.tipo} for ramo in rami]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Runner nazionale avvisi, resumable e senza LLM")
    parser.add_argument("--istats-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data-live/notices"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument(
        "--min-completed",
        type=int,
        default=0,
        help="Valuta la soglia di copertura solo dopo questo numero di comuni.",
    )
    parser.add_argument(
        "--max-non-coperto-rate",
        type=float,
        help="Interrompe e conserva review se la quota non_coperto e' superiore alla soglia.",
    )
    args = parser.parse_args(argv)
    if args.min_completed < 0:
        parser.error("--min-completed deve essere >= 0")
    if args.max_non_coperto_rate is not None and not 0 <= args.max_non_coperto_rate <= 1:
        parser.error("--max-non-coperto-rate deve essere tra 0 e 1")
    checkpoint = args.checkpoint or args.output / "run-checkpoint.json"
    report = run(load_codes(args.istats_file), store=NoticeStore(args.output), checkpoint=checkpoint,
                 delay_seconds=max(0.0, args.delay_seconds),
                 min_completed=args.min_completed,
                 max_non_coperto_rate=args.max_non_coperto_rate)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
