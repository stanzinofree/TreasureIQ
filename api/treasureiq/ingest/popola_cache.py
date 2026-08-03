"""Populate the web-search cache for every topic, one comune at a time.

Usage:
    python -m treasureiq.ingest.popola_cache [--comune "Albano Laziale" ...]
                                             [--pausa 15] [--tentativi 3]
                                             [--out /out]

With `BRAVE_SEARCH_API_KEY` in the environment the queries go through the
Brave Search API and `--pausa` can drop to a second or two — the quota is
published and there is no bot detection to trip. Without it they fall back to
SearXNG, where the pacing matters and the default is deliberately slow.

Why this exists rather than a loop at the call site: the upstream engines
SearXNG federates to rate-limit hard. Forty queries fired back to back earned
`suspended_time=180` from both Google CSE and Brave, after which every search
returned zero results — indistinguishable, from the caller's side, from "this
comune has published nothing", which is the one confusion this project cannot
afford. So requests are paced, empty answers are retried after a longer wait,
and anything still empty at the end is reported as unresolved rather than
cached as an absence.

Writes are ordinary cache entries; nothing here touches the runtime, which
only ever reads what this produced (D-28).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from treasureiq.chat.respond import WEBSEARCH_QUERY_FRAGMENTS
from treasureiq.ingest.websearch import run_and_cache

DEFAULT_COMUNI = ("Albano Laziale", "Fonte Nuova")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--comune", action="append", default=None)
    p.add_argument("--pausa", type=float, default=15.0, help="secondi fra due query")
    p.add_argument("--tentativi", type=int, default=3)
    p.add_argument("--out", default="/out", help="cartella cache scrivibile")
    p.add_argument("--base-url", default="http://searxng:8080")
    args = p.parse_args(argv)

    comuni = args.comune or list(DEFAULT_COMUNI)
    cache = Path(args.out)
    cache.mkdir(parents=True, exist_ok=True)

    lavori = [
        (f"{frag} {comune}", topic.value, comune)
        for topic, frag in WEBSEARCH_QUERY_FRAGMENTS.items()
        for comune in comuni
    ]
    print(f"{len(lavori)} query, pausa {args.pausa}s, cache in {cache}", flush=True)

    irrisolte: list[str] = []
    for i, (query, topic, comune) in enumerate(lavori, 1):
        risultati = 0
        for tentativo in range(1, args.tentativi + 1):
            if i > 1 or tentativo > 1:
                # Back off harder on a retry: an empty answer usually means the
                # engines are suspended, and asking again immediately extends
                # the suspension instead of clearing it.
                time.sleep(args.pausa * (2 if tentativo > 1 else 1))
            try:
                entry = run_and_cache(query, cache_dir=cache, base_url=args.base_url, timeout=30.0)
                risultati = len(entry.results)
            except Exception as exc:  # noqa: BLE001 — reported, not swallowed
                print(f"  [{i}/{len(lavori)}] ERRORE {type(exc).__name__}: {query}", flush=True)
                continue
            if risultati:
                break

        stato = f"{risultati} risultati" if risultati else "VUOTA"
        print(f"  [{i}/{len(lavori)}] {stato:14} {topic:26} {query}", flush=True)
        if not risultati:
            irrisolte.append(query)

    print(f"\nfatte {len(lavori)}, senza risultati istituzionali {len(irrisolte)}", flush=True)
    for q in irrisolte:
        print(f"  irrisolta: {q}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
