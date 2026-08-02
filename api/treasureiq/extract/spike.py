"""D-07 measurement spike: quote-gated extraction discard rate on real pages.

Runs the same `RequirementsExtractor` that ingestion will use, but against
Albano's `pages` collection (bandi/concorsi/volontariato prose that has no
CMB2 typed fields at all — see spec D-03/D-07) instead of `servizi`. The
question this answers: does Qwen, under the mandatory quote-gate (D-05),
recover enough structured fields from that prose to be worth wiring into
ingestion, or does the plan need to fall back to Anthropic per D-06/D-08
before any chat code is written?

This is a one-shot measurement tool, not a connector: it does not write to
`data/seed/`, and it is not imported by anything else. `ingest/wp_pages.py`
(Wave 2, brief B4) is the real connector; this script exists only to produce
`.kapi/spike-d07.md` before that work starts.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from treasureiq.extract.llm import RequirementsExtractor
from treasureiq.extract.providers import load_provider
from treasureiq.ingest.base import USER_AGENT
from treasureiq.ingest.wp_comuni import strip_html

logger = logging.getLogger(__name__)

ALBANO_BASE_URL = "https://comune.albanolaziale.rm.it"
SEARCH_KEYWORDS = [
    "bando",
    "avviso pubblico",
    "concorso",
    "volontariato",
    "contributo",
    "borsa",
]

# Fields an ExtractionResult can populate. Kept in one place so per-field
# populate/discard counts and the printed report agree on the same list.
#
# Read off the RAW `ExtractionResult` (pre-`to_requirements()`), not the
# converted `Requirements` object: `Requirements.residenza_required` defaults
# to `True` in the schema (municipal benefits almost always require it —
# schema.py:140-143) whenever the source is silent, which would make every
# page look "populated" on that field regardless of what the model actually
# quoted. The raw model output has no such default (`None` until the model
# says otherwise), so it is the only place "populated" means "the model made
# a claim and it survived the quote-gate", matching `llm.py`'s own
# `supported()` check.
TRACKED_FIELDS = [
    "isee_max",
    "isee_min",
    "eta_min",
    "eta_max",
    "nucleo_min",
    "figli_minori_required",
    "disabilita_required",
    "residenza_required",
    "employment_status",
    "other",
    "deadline_iso",
]


def _is_claimed(value: object) -> bool:
    """Whether the raw model output made a (non-empty) claim for this field."""
    if value is None:
        return False
    if isinstance(value, (list, str)) and len(value) == 0:
        return False
    return True


@dataclass
class PageResult:
    """What the spike learned about extracting from one prose page."""

    page_id: int
    title: str
    populated: list[str] = field(default_factory=list)
    discarded: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    failed: bool = False

    @property
    def has_gated_requirement(self) -> bool:
        return bool(self.populated)


def fetch_candidate_pages(*, base_url: str, limit: int) -> list[dict[str, Any]]:
    """Fetch and dedupe Albano `pages` matching the six spike keywords.

    Fail-soft per keyword, matching the connector convention in
    `ingest/base.py`: one bad search must not take the whole spike down.
    """
    seen: dict[int, dict[str, Any]] = {}
    with httpx.Client(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        for keyword in SEARCH_KEYWORDS:
            if len(seen) >= limit:
                break
            try:
                response = client.get(
                    f"{base_url}/wp-json/wp/v2/pages",
                    params={"search": keyword, "per_page": 20},
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                logger.warning("search %r failed: %s", keyword, exc)
                continue
            if not isinstance(payload, list):
                logger.warning("search %r: unexpected payload shape", keyword)
                continue
            for record in payload:
                page_id = record.get("id")
                if page_id is None or page_id in seen:
                    continue
                seen[page_id] = record

    ordered = list(seen.values())
    return ordered[:limit]


def run_spike(*, pages: int, provider_override: str | None, verbose: bool) -> list[PageResult]:
    if provider_override:
        import os

        os.environ["TREASUREIQ_LLM_PROVIDER"] = provider_override

    provider = load_provider(role="extract")
    print(f"provider: {provider.name} (available={provider.available})")

    repo_root = Path(__file__).resolve().parents[3]
    extractor = RequirementsExtractor(repo_root / "data" / "extraction-cache", provider=provider)

    print(f"fetching up to {pages} Albano pages for keywords: {', '.join(SEARCH_KEYWORDS)}")
    records = fetch_candidate_pages(base_url=ALBANO_BASE_URL, limit=pages)
    print(f"fetched {len(records)} distinct pages\n")

    results: list[PageResult] = []
    for record in records:
        page_id = record.get("id")
        title = strip_html(record.get("title", {}).get("rendered", "")).strip() or f"page {page_id}"
        raw_content = record.get("content", {}).get("rendered", "")
        text = strip_html(raw_content)

        result = PageResult(page_id=page_id, title=title)
        start = time.monotonic()
        try:
            outcome = extractor.extract(
                text=text,
                title=title,
                raw_hash=f"spike-{page_id}",
            )
        except Exception as exc:  # spike must survive one bad page (fail-soft)
            logger.warning("extraction crashed for page %s: %s", page_id, exc)
            result.failed = True
            result.notes.append(f"extraction raised: {exc}")
            outcome = None
        result.elapsed_s = time.monotonic() - start

        if outcome is None:
            result.notes.append("extractor returned no result (skipped or failed)")
        else:
            _req, notes, _confidence = outcome
            result.notes.extend(notes)

            # `extract()` already wrote the raw model output to the on-disk
            # cache keyed by `raw_hash` (llm.py `ExtractionCache.put`); read
            # it straight back to inspect the model's claims and quotes
            # before `to_requirements()` folds them into the schema (and, for
            # `residenza_required`, applies its default — see TRACKED_FIELDS
            # comment above).
            raw = extractor.cache.get(f"spike-{page_id}")
            if raw is None:
                result.notes.append("no raw cache entry found for gate inspection")
            else:
                quoted = raw.quoted_fields()
                for field_name in TRACKED_FIELDS:
                    value = getattr(raw, field_name, None)
                    if not _is_claimed(value):
                        continue
                    if field_name in quoted:
                        result.populated.append(field_name)
                    else:
                        result.discarded.append(
                            f"'{field_name}' claimed ({value!r}) but no quote given"
                        )

        results.append(result)

        print(f"[page {page_id}] {title[:70]}")
        print(f"  populated: {result.populated or '(none)'}")
        print(f"  discarded: {len(result.discarded)}")
        if result.discarded and verbose:
            for line in result.discarded:
                print(f"    - {line}")
        if result.notes and verbose:
            for line in result.notes:
                print(f"  note: {line}")
        print(f"  elapsed: {result.elapsed_s:.1f}s")
        print()

    return results


def summarise(results: list[PageResult]) -> str:
    total = len(results)
    if total == 0:
        return "no pages fetched — cannot measure anything."

    with_gated = sum(1 for r in results if r.has_gated_requirement)
    pct = 100.0 * with_gated / total

    populate_counts: dict[str, int] = {f: 0 for f in TRACKED_FIELDS}
    for r in results:
        for f_name in r.populated:
            populate_counts[f_name] += 1
    total_discards = sum(len(r.discarded) for r in results)
    total_wall = sum(r.elapsed_s for r in results)
    avg_wall = total_wall / total

    lines = [
        f"pages measured: {total}",
        f"pages with >=1 quote-gated requirement: {with_gated} ({pct:.1f}%)",
        f"total wall-clock: {total_wall:.1f}s, avg per page: {avg_wall:.1f}s",
        "per-field populate counts:",
    ]
    for f_name, count in populate_counts.items():
        lines.append(f"  {f_name}: {count}")
    lines.append(f"total discard notes (quote-gate rejections): {total_discards}")
    lines.append(f"threshold: >=40% => GO ollama; <40% => NO-GO, flip to anthropic")
    lines.append("DECISION: " + ("GO — ollama" if pct >= 40.0 else "NO-GO — ollama"))

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.extract.spike",
        description=(
            "D-07 measurement spike: run the quote-gated RequirementsExtractor "
            "against real Albano 'pages' (prose bandi/concorsi/volontariato "
            "content with no CMB2 typed fields) and report the discard rate "
            "under the mandatory quote-gate (D-05), to decide GO/NO-GO on "
            "Ollama for ingestion extraction (D-06/D-07/D-08)."
        ),
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=15,
        help="number of distinct Albano pages to measure (default: 15)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="override TREASUREIQ_LLM_PROVIDER for this run (e.g. 'ollama' or 'anthropic')",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print discard notes and extraction notes per page",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    results = run_spike(pages=args.pages, provider_override=args.provider, verbose=args.verbose)

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(summarise(results))


if __name__ == "__main__":
    main()
