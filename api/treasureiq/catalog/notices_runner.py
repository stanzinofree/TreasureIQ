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
from treasureiq.catalog.store import _atomic_write


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
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Persist each outcome and checkpoint after every municipality."""
    try:
        state = json.loads(checkpoint.read_text("utf-8")) if checkpoint.exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    completed = set(state.get("completed") or [])
    errors = dict(state.get("errors") or {})
    discover = producer or (lambda code: produce(code, store=store))

    for code in codes:
        if code in completed:
            continue
        try:
            snapshot = discover(code)
            store.save(snapshot)
            completed.add(code)
            errors.pop(code, None)
        except Exception as exc:  # an individual portal cannot stop the national run
            errors[code] = type(exc).__name__
        _atomic_write(
            checkpoint,
            json.dumps(
                {"completed": sorted(completed), "errors": errors},
                ensure_ascii=False,
                indent=1,
            ) + "\n",
        )
        if delay_seconds:
            sleep(delay_seconds)

    statuses = Counter()
    for code in completed:
        snapshot = store.load(code)
        if snapshot is not None:
            statuses[snapshot.coverage_status] += 1
    return {"completed": len(completed), "errors": errors, "coverage": dict(statuses)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Runner nazionale avvisi, resumable e senza LLM")
    parser.add_argument("--istats-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data-live/notices"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    checkpoint = args.checkpoint or args.output / "run-checkpoint.json"
    report = run(load_codes(args.istats_file), store=NoticeStore(args.output), checkpoint=checkpoint,
                 delay_seconds=max(0.0, args.delay_seconds))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
