"""Web-search fallback for the `M6_web_aperto` rung (D-28), Brave-only (D-59).

When every institutional source is exhausted on the INFORMAZIONE rail — no
typed field, no CKAN dataset, no scrapeable page — the last thing TreasureIQ
can offer is a link to check yourself. This module is how that link gets
found, at ingestion time (`run_and_cache`, committed to disk) and — per D-59
— also live, through the same `search_brave` client the chat rail calls.

**Brave Search API is now the only engine.** It is sanctioned automated
access: a documented endpoint with a published quota, rather than a
meta-search whose upstreams decide query by query whether today's traffic
looks like a robot. SearXNG used to be the no-key fallback under `docker
compose --profile ingest`, but forty paced queries once earned simultaneous
suspensions from every engine behind it, after which each search returned
nothing — and nothing is precisely what this project must never mistake for
an absence. D-59 removes that fallback rather than keep tolerating it:
without `BRAVE_SEARCH_API_KEY` there is no search, ever — `search_web` raises
`WebSearchNonConfigurato` instead of degrading to a second, less trustworthy
engine.

The key is read from the environment and handed straight to a request header.
It is never written into this repository, a settings file, or a log line.

Three properties make this safe rather than merely convenient (R-15, the
highest risk in the project — a fabricated or stale web result handed to a
citizen as if it were an answer):

1. **Never invented.** `WebSearchNonConfigurato` (missing key) and any HTTP
   failure both propagate to the caller unhandled; nothing here catches an
   error and substitutes a hand-written result. The caller (`chat/respond`,
   B3b) is the one that decides how "no search available" reads to a
   citizen — this module only ever returns real hits or raises.
2. **Verbatim, and nothing else.** Only `title` and `url` are read out of
   Brave's response and stored. No snippet, no description, no summary — if
   there is no prose on disk, no prose can reach the model. `chat/respond`
   (D-24) composes the citizen-facing sentence around these two fields; it
   never paraphrases them.
3. **Cache is a dated hint, never a silent source of truth.** `fetched_at` on
   every cache entry lets a caller judge freshness explicitly; `entro_ttl`
   below is the interface B3b uses to decide whether a cached hit is still
   within `TTL_GIORNI` days or should be shown as stale (D-60). A connection
   error or a non-200 response during ingestion aborts with a non-zero exit
   and writes nothing — the previous cache entry, if any, survives untouched.
   A 200 with zero hits is a real, cacheable-but-not-cached answer (see
   `run_and_cache`); at runtime, a missing or empty cache entry renders as
   "nessun risultato", never a fabricated link.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
MAX_RESULTS = 3

#: D-60: how long a cached web-search hit is treated as a fresh-enough hint.
#: Past this many days `entro_ttl` reports the entry as stale; the policy of
#: what a stale entry looks like to a citizen (hint + visible timestamp) is
#: applied by the caller (B3b), not here.
TTL_GIORNI = 7

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

DEFAULT_TIMEOUT = 15.0


class WebResult(BaseModel):
    """One search hit, verbatim. Title and URL only — see module docstring."""

    title: str
    url: str


class WebSearchCacheEntry(BaseModel):
    """What a query resolved to, and when.

    `fetched_at` is dated so a stale result is auditable rather than assumed
    fresh; `provider` records which search backend produced it — always
    `"brave"` since D-59, but the field stays so old cache entries written
    under the SearXNG era still validate and remain auditable.
    """

    query: str
    provider: str
    fetched_at: datetime
    results: list[WebResult]


def entro_ttl(entry: WebSearchCacheEntry, oggi: datetime) -> bool:
    """Whether `entry` is still within `TTL_GIORNI` days of `oggi` (D-60).

    Pure date arithmetic on `fetched_at` — no network, no side effect. This
    is only the interface: what a caller *does* with a stale entry (still
    show it, but marked, or drop it) is B3b's policy, not this function's.
    """
    return (oggi - entry.fetched_at) <= timedelta(days=TTL_GIORNI)


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


BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

#: Name of the environment variable holding the Brave Search API key. The key
#: itself never appears in this repository, in a settings file, or in a log
#: line: it is read from the environment at ingestion time and passed straight
#: to the request header.
BRAVE_KEY_ENV = "BRAVE_SEARCH_API_KEY"


class WebSearchNonConfigurato(RuntimeError):
    """`BRAVE_SEARCH_API_KEY` is not set — no engine is available (D-59).

    Brave is the only search provider; there is no second engine to fall
    back to. The caller must degrade this to "nessuna ricerca web
    disponibile" for the citizen — never catch it and invent a result
    (D-28/R-15), and never mistake it for a query that ran and found
    nothing.
    """


def _filtra(
    grezzi: list[tuple[str | None, str | None]], *, query: str, provider: str
) -> list[WebResult]:
    """Keep the public-body results, in order, up to `MAX_RESULTS`.

    Filtering happens before the top-N cut. Slicing first would let three
    commercial pages consume the whole budget and return nothing — which reads,
    from the caller's side, exactly like "nothing published on this", the one
    confusion this project cannot afford.
    """
    tenuti: list[WebResult] = []
    scartati = 0
    for title, url in grezzi:
        if not title or not url:
            continue
        if not is_institutional(url):
            scartati += 1
            continue
        tenuti.append(WebResult(title=title, url=url))
        if len(tenuti) == MAX_RESULTS:
            break
    if scartati:
        logger.info(
            "%s %r: %d risultati non istituzionali scartati, %d tenuti",
            provider,
            query,
            scartati,
            len(tenuti),
        )
    return tenuti


def search_brave(
    query: str,
    *,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[WebResult]:
    """Run one query against the Brave Search API — the only engine (D-59).

    *Sanctioned* automated access: a documented endpoint with a published
    quota, unlike the old meta-search fallback whose upstreams decided, query
    by query, whether today's traffic looked like a robot. Firing forty paced
    queries through that once earned suspensions from every engine at once
    and returned empty results — which this project must never mistake for
    an absence.

    Raises on any connection error or non-200: per D-28/R-15 the caller must
    not substitute a hand-written result, and an exception is the only signal
    that cannot be confused with "found nothing".
    """
    response = httpx.get(
        BRAVE_ENDPOINT,
        params={"q": query, "country": "IT", "search_lang": "it", "count": 20},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    grezzi = [
        (hit.get("title"), hit.get("url"))
        for hit in (payload.get("web") or {}).get("results") or []
    ]
    return _filtra(grezzi, query=query, provider="brave")


def search_web(
    query: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[list[WebResult], str]:
    """Search with Brave — the only provider since D-59 — and say so.

    The provider still travels with the results because it belongs in the
    cache entry for audit purposes (older entries may carry `"searxng"`),
    even though every entry written from here on is `"brave"`.

    Raises `WebSearchNonConfigurato` if `BRAVE_SEARCH_API_KEY` is unset —
    never falls back to a second engine, never returns an empty list to mean
    "not configured" (that would be indistinguishable from a real zero-hit
    answer). The caller decides how that reads to a citizen; this function
    only ever returns real hits or raises.
    """
    chiave = os.environ.get(BRAVE_KEY_ENV, "").strip()
    if not chiave:
        raise WebSearchNonConfigurato(
            f"{BRAVE_KEY_ENV} non impostata: nessun motore di ricerca disponibile"
        )
    return search_brave(query, api_key=chiave, timeout=timeout), "brave"


def run_and_cache(
    query: str,
    *,
    cache_dir: Path,
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
    results, provider = search_web(query, timeout=timeout)
    entry = WebSearchCacheEntry(
        query=query,
        provider=provider,
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
            "Run one web search against Brave and cache the result "
            "(title + URL only). D-59: Brave is the only engine; "
            f"requires {BRAVE_KEY_ENV} in the environment."
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
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    cache_dir = args.cache_dir or _default_cache_dir()

    if args.comune:
        logger.info("query for comune %s: %s", args.comune, args.query)

    try:
        results, provider = search_web(args.query)
    except Exception as exc:
        # WebSearchNonConfigurato, connection error, or non-200: exit
        # non-zero, write nothing. The previous cache entry, if any, is left
        # untouched.
        print(f"web search failed for {args.query!r}: {exc}", file=sys.stderr)
        return 1

    if args.write:
        entry = WebSearchCacheEntry(
            query=args.query,
            provider=provider,
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
