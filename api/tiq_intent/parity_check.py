"""Parity gate + benchmark for the Rust `tiq_intent` crate vs its Python oracle.

Usage (inside the `dev` stage container, from `/src` == repo's `api/`):

    python tiq_intent/parity_check.py

Runs every case in `cases.json` through both `tiq_intent.score` (native,
PyO3) and `treasureiq.chat.intent_scorer.score_intent` (the oracle),
prints PASS/FAIL per case, and exits non-zero if any case diverges. If all
cases pass, benchmarks both implementations on a fixed message and prints
µs/call plus the speedup factor.

This script does NOT modify intent_scorer.py, taxonomy.toml, or cases.json.
It is read-only with respect to the oracle, by design (parity is the gate:
Rust conforms to Python, never the other way around).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent

try:
    import tiq_intent  # native PyO3 module, must be importable (pip installed as a wheel)
except ImportError as exc:  # pragma: no cover - operator-facing diagnostic
    print(f"FAIL: cannot import native module 'tiq_intent': {exc}", file=sys.stderr)
    print(
        "Build it first (maturin build --release) and pip install the wheel.",
        file=sys.stderr,
    )
    sys.exit(2)

from treasureiq.chat.intent_scorer import score_intent as py_score_intent


def load_cases() -> list[dict]:
    with (_HERE / "cases.json").open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data["cases"]


def run_parity(cases: list[dict]) -> bool:
    all_ok = True
    for i, case in enumerate(cases, start=1):
        msg = case["msg"]
        expected_topic = case["topic"] if case["topic"] is not None else "sconosciuto"
        expected_kind = case["kind"]

        py_result = py_score_intent(msg)
        native_topic, native_kind, native_conf = tiq_intent.score(msg)

        topic_kind_match = (
            py_result.topic == native_topic
            and py_result.kind == native_kind
            and native_topic == expected_topic
            and native_kind == expected_kind
        )
        conf_match = abs(py_result.confidence - native_conf) < 1e-9
        ok = topic_kind_match and conf_match

        status = "PASS" if ok else "FAIL"
        print(
            f"[{status}] case {i:2d}: {msg!r}\n"
            f"          expected=({expected_topic}, {expected_kind})\n"
            f"          python  =({py_result.topic}, {py_result.kind}, {py_result.confidence:.6f})\n"
            f"          native  =({native_topic}, {native_kind}, {native_conf:.6f})"
        )
        if not ok:
            all_ok = False
    return all_ok


def run_benchmark(n: int = 100_000) -> None:
    message = "non riesco a pagare le bollette della luce, ho diritto a un bonus?"

    # score_intent is @lru_cache(maxsize=2048): calling it N times on the SAME
    # message would benchmark a dict lookup after the first call, not the
    # scorer. tiq_intent.score has no result-level cache (only the compiled
    # regex matcher cache, which both sides warm up identically), so a fair
    # comparison uses score_intent's *unwrapped* function to measure the
    # scorer itself, not Python's memoization.
    py_score_fn = py_score_intent.__wrapped__

    # Warm up both (matcher regex caches on each side) before timing.
    py_score_fn(message)
    tiq_intent.score(message)

    start = time.perf_counter()
    for _ in range(n):
        py_score_fn(message)
    py_elapsed = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(n):
        tiq_intent.score(message)
    native_elapsed = time.perf_counter() - start

    py_us = (py_elapsed / n) * 1_000_000
    native_us = (native_elapsed / n) * 1_000_000
    speedup = py_elapsed / native_elapsed if native_elapsed > 0 else float("inf")

    print()
    print(f"Benchmark: N={n} calls, message={message!r}")
    print(f"  python (score_intent, lru_cache disabled): {py_us:.3f} us/call  ({py_elapsed:.3f}s total)")
    print(f"  native (tiq_intent.score):                 {native_us:.3f} us/call  ({native_elapsed:.3f}s total)")
    print(f"  speedup: {speedup:.1f}x")


def main() -> int:
    # The benchmark (speedup ~6-7x) is environment-variable and must never gate
    # CI: `--no-benchmark` runs only the 35-case parity and exits on that alone.
    no_benchmark = "--no-benchmark" in sys.argv[1:]
    cases = load_cases()
    print(f"Running parity check on {len(cases)} golden cases...\n")
    ok = run_parity(cases)
    print()
    if not ok:
        print(f"PARITY FAILED", file=sys.stderr)
        return 1
    print(f"PARITY OK: {len(cases)}/{len(cases)} cases match.")
    if not no_benchmark:
        run_benchmark()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
