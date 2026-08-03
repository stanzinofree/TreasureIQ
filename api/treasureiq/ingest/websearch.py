"""Ingestion-time web-search fallback for the `M6_web_aperto` rung (D-28).

When every institutional source is exhausted on the INFORMAZIONE rail — no
typed field, no CKAN dataset, no scrapeable page — the last thing TreasureIQ
can offer is a link to check yourself. This module is how that link gets
found: a query against a self-hosted SearXNG instance, run **at ingestion
only**, its result cached to disk and committed.

Three properties make this safe rather than merely convenient (R-15, the
highest risk in the project — a fabricated or stale web result handed to a
citizen as if it were an answer):

1. **No network at runtime.** `load_cached` only reads a committed JSON file.
   The search itself (`search_searxng`, `run_and_cache`) never runs from the
   API process — only from this module's CLI, invoked by hand during
   ingestion. `compose.yml` keeps `searxng` behind `profiles: ["ingest"]` so
   a plain `docker compose up` never even starts the service that could make
   a live call possible.
2. **Verbatim, and nothing else.** Only `title` and `url` are read out of
   SearXNG's response and stored. No snippet, no description, no summary —
   if there is no prose on disk, no prose can reach the model. `chat/respond`
   (D-24) composes the citizen-facing sentence around these two fields; it
   never paraphrases them.
3. **Never a guess.** A connection error or a non-200 response aborts with a
   non-zero exit and writes nothing — the previous cache entry, if any,
   survives untouched. A 200 with zero hits is a real, cacheable answer
   (`results: []`); it means the web genuinely has nothing, which is itself
   informative. At runtime, a missing or empty cache entry renders as
   "nessun risultato", never a fabricated link.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
MAX_RESULTS = 3

#: Only these hosts may reach a citizen. An open web search for "bonus sociale
#: bollette Albano Laziale" returns, above the real ones, a commercial energy
#: blog and a Facebook group — and this rail exists precisely for the moments
#: when the institutional sources ran out, which is when a citizen is least
#: able to tell the difference. A result outside this list is dropped, never
#: shown with a warning: a page presented as an answer is trusted whatever the
#: label says.
#:
#: Suffix match on the host, so `comune.albanolaziale.rm.it` passes via
#: `.rm.it`-less rules below and `notgov.it` cannot pass as `gov.it`.
ISTITUZIONALI: tuple[str, ...] = (
    ".gov.it",
    ".gob.it",
    "inps.it",
    "arera.it",
    "agenziaentrate.gov.it",
    "lavoro.gov.it",
    "salute.gov.it",
    "regione.lazio.it",
    "cittametropolitanaroma.it",
    "anci.it",
    "europa.eu",
)

#: Municipal sites do not share one suffix, so they are recognised by shape:
#: `comune.<qualcosa>.<provincia>.it` and the handful of variants Italian
#: comuni actually use.
_COMUNE_HOST = ("comune.", "comuni.", "citta.", "cittadi.")


def is_institutional(url: str) -> bool:
    """Whether a URL belongs to a public body.

    Deliberately strict and deliberately dumb: an allowlist of suffixes plus a
    municipal host shape. Anything clever here — scoring, "looks official",
    trusting the search engine's own ranking — would eventually let a
    convincing commercial page through, and the whole point of this filter is
    that a citizen who has run out of institutional sources cannot afford to
    adjudicate that themselves.
    """
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    host = host.lower().removeprefix("www.")
    if any(host == s.lstrip(".") or host.endswith(s) for s in ISTITUZIONALI):
        return True
    return any(host.startswith(p) for p in _COMUNE_HOST) and host.endswith(".it")

DEFAULT_SEARXNG_URL = "http://localhost:8080"
DEFAULT_TIMEOUT = 15.0

PROVIDER = "searxng"


class WebResult(BaseModel):
    """One search hit, verbatim. Title and URL only — see module docstring."""

    title: str
    url: str


class WebSearchCacheEntry(BaseModel):
    """What a query resolved to, and when.

    `fetched_at` is dated so a stale result is auditable rather than assumed
    fresh; `provider` records which search backend produced it, since D-28
    names SearXNG as the no-key default with Brave as a paid alternative.
    """

    query: str
    provider: str
    fetched_at: datetime
    results: list[WebResult]


def cache_key(query: str) -> str:
    """Stable filename stem for a query, independent of whitespace/case noise."""
    normalised = " ".join(query.strip().lower().split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def cache_path(query: str, cache_dir: Path) -> Path:
    return cache_dir / f"{cache_key(query)}.v{CACHE_VERSION}.json"


def load_cached(query: str, cache_dir: Path) -> WebSearchCacheEntry | None:
    """Read-only lookup for the runtime path. Never touches the network.

    Returns `None` on a missing file, an empty/corrupt file, or a validation
    failure — every one of those cases must degrade to "nessun risultato" at
    the call site, never to a fabricated result.
    """
    path = cache_path(query, cache_dir)
    if not path.exists():
        return None
    try:
        return WebSearchCacheEntry.model_validate_json(path.read_text("utf-8"))
    except Exception as exc:
        logger.warning("discarding unreadable websearch cache entry %s: %s", path.name, exc)
        return None


def search_searxng(
    query: str,
    *,
    base_url: str = DEFAULT_SEARXNG_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[WebResult]:
    """Run one query against a SearXNG instance and return up to 3 hits.

    Raises on any connection error or non-200 response — the caller must not
    catch this and fall back to a hand-written result; per D-28/R-15, no
    result is better than an invented one.
    """
    response = httpx.get(
        f"{base_url.rstrip('/')}/search",
        params={"q": query, "format": "json"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()

    # Filter first, then take the top few. Slicing before filtering would let
    # three commercial pages consume the whole budget and return nothing, which
    # is how this rail would silently go quiet exactly when it is needed.
    results: list[WebResult] = []
    scartati = 0
    for hit in payload.get("results", []):
        title = hit.get("title")
        url = hit.get("url")
        if not title or not url:
            continue
        if not is_institutional(url):
            scartati += 1
            continue
        results.append(WebResult(title=title, url=url))
        if len(results) == MAX_RESULTS:
            break

    if scartati:
        logger.info(
            "web search %r: %d risultati non istituzionali scartati, %d tenuti",
            query,
            scartati,
            len(results),
        )
    return results


def run_and_cache(
    query: str,
    *,
    cache_dir: Path,
    base_url: str = DEFAULT_SEARXNG_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> WebSearchCacheEntry:
    """Search, then persist the entry. Called only from ingestion.

    A connection error or non-200 propagates to the caller unhandled — the
    CLI turns that into a non-zero exit and writes nothing (D-28's
    degradation rule).

    An empty result set is *not* written either, and that is the important
    part. A 200 with zero hits does not mean the web holds nothing on the
    subject; in practice it has meant the upstream engines were rate-limiting
    or serving a CAPTCHA, and forty such entries were once cached in a single
    run. Persisted, they are indistinguishable at read time from a genuine
    absence — and this project states absences to citizens as findings. An
    absence we cannot tell apart from a failure must not be recorded as one,
    so the cache stays silent and the caller sees an empty entry it can
    retry.
    """
    results = search_searxng(query, base_url=base_url, timeout=timeout)
    entry = WebSearchCacheEntry(
        query=query,
        provider=PROVIDER,
        fetched_at=datetime.now(timezone.utc),
        results=results,
    )
    if not results:
        logger.warning(
            "web search %r returned nothing — not cached: an empty answer here "
            "usually means the engines refused us, not that nothing exists",
            query,
        )
        return entry
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path(query, cache_dir).write_text(
        entry.model_dump_json(indent=1), encoding="utf-8"
    )
    return entry


def _default_cache_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "websearch-cache"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one web search against SearXNG and cache the result "
            "(title + URL only). Ingestion-time only, D-28."
        )
    )
    parser.add_argument("query", help="Search query, e.g. 'calendario raccolta vetro Ariccia'")
    parser.add_argument(
        "--comune",
        default=None,
        help="Codice ISTAT of the comune this query is for, recorded in logs only.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist the result to data/websearch-cache/. Without this, dry-run only.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SEARXNG_URL", DEFAULT_SEARXNG_URL),
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    cache_dir = args.cache_dir or _default_cache_dir()

    if args.comune:
        logger.info("query for comune %s: %s", args.comune, args.query)

    try:
        results = search_searxng(args.query, base_url=args.base_url)
    except Exception as exc:
        # Connection error or non-200: exit non-zero, write nothing. The
        # previous cache entry, if any, is left untouched.
        print(f"web search failed for {args.query!r}: {exc}", file=sys.stderr)
        return 1

    if args.write:
        entry = WebSearchCacheEntry(
            query=args.query,
            provider=PROVIDER,
            fetched_at=datetime.now(timezone.utc),
            results=results,
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_path(args.query, cache_dir)
        path.write_text(entry.model_dump_json(indent=1), encoding="utf-8")
        print(f"wrote {path} ({len(results)} results)")
    else:
        print(json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=1))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
