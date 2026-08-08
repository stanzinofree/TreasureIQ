"""Shared PDF-download + corpus-assembly pipeline (D-08, D-15).

Extracted from `ingest/wp_pages.py` (`.kapi/plan.md` brief B1) so both the WP
ingest connector and the future live bandi engine (`bandi_live`, B2) build
their `Segment` corpus through one budgeted, audited path instead of two
copies that could drift apart.

Two entry points:
- `collect_pdf_segments` — downloads up to `MAX_PDFS_PER_PAGE` linked PDFs
  (subject to `MAX_PDF_BYTES`), extracts text via `pypdf`, and audits every
  skip (cap reached, too large, download failed, unreadable) as a `PdfSkip`
  plus a human-readable note (D-15: "log every skip explicitly").
- `build_corpus` — assembles the page body and any opened PDF pages into one
  boundary-tracked corpus (`Segment` per unit), then truncates to
  `MAX_CORPUS_CHARS` and slices the segment list down to what the model
  actually saw, per D-15's cap. A quote can never be legitimately attributed
  to a segment (or the tail of a segment) beyond that truncation point.

Callers own the transport (`httpx.Client`) and the `base_url` used to resolve
relative PDF links — this module does not construct or cache a client, so it
carries no assumptions about connector lifecycle.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

import httpx

from treasureiq.extract.llm import Segment
from treasureiq.schema import PdfSkip

logger = logging.getLogger(__name__)

#: D-15 budget knobs — hard caps that keep a full run in minutes, not hours.
MAX_PDFS_PER_PAGE = 5
MAX_PDF_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_CORPUS_CHARS = 12_000

#: Filenames far more likely to carry eligibility criteria than
#: administrative boilerplate (D-15) — a preference order, not an exclusion:
#: a deprioritised PDF is still opened if the per-page slot allows it.
_PREFERRED_FILENAME_RE = re.compile(r"bando|avviso|regolament", re.IGNORECASE)
_DEPRIORITISED_FILENAME_RE = re.compile(r"modulo|domanda|allegat", re.IGNORECASE)


def _filename_rank(url: str) -> int:
    """Lower sorts first: preferred filenames before neutral before deprioritised."""
    if _PREFERRED_FILENAME_RE.search(url):
        return 0
    if _DEPRIORITISED_FILENAME_RE.search(url):
        return 2
    return 1


def collect_pdf_segments(
    client: httpx.Client,
    base_url: str,
    pdf_urls: list[str],
) -> tuple[list[dict[str, Any]], list[str], list[PdfSkip], int]:
    """Download and extract text from up to `MAX_PDFS_PER_PAGE` attachments.

    `pypdf` is imported lazily (only pages that actually link a PDF pay this
    cost, matching `extract/llm.py`'s lazy-import convention for
    `anthropic`). Every skip — cap reached, too large, download failure,
    unreadable — is logged and returned as a human-readable note, per D-15:
    "log every skip explicitly."

    Also returns the D-16 skip audit (`PdfSkip` per skip) and how many of
    those skips were a genuine readability failure (parse failure or no
    extractable text) rather than a budget choice (cap reached, too large) or
    a transient network failure (download failed) — this distinction is what
    separates `L3_illeggibile` from a plain `L1_manuale` for callers building
    a `RecoveryLevel`.
    """
    notes: list[str] = []
    skipped: list[PdfSkip] = []
    illegible_count = 0
    if not pdf_urls:
        return [], notes, skipped, illegible_count

    def _skip(absolute_url: str, note: str, reason: str, *, illegible: bool) -> None:
        nonlocal illegible_count
        logger.info("skipping PDF %s: %s", absolute_url, reason)
        notes.append(note)
        skipped.append(PdfSkip(url=absolute_url, reason=reason))
        if illegible:
            illegible_count += 1

    ranked = sorted(dict.fromkeys(pdf_urls), key=_filename_rank)

    segments: list[dict[str, Any]] = []
    opened = 0
    for url in ranked:
        absolute_url = url if url.startswith("http") else f"{base_url}{url}"

        if opened >= MAX_PDFS_PER_PAGE:
            reason = f"limite di {MAX_PDFS_PER_PAGE} allegati per pagina raggiunto"
            _skip(
                absolute_url,
                f"Allegato PDF ignorato ({reason}): {absolute_url}",
                reason,
                illegible=False,
            )
            continue

        content_length = 0
        try:
            head = client.head(absolute_url)
            content_length = int(head.headers.get("content-length", 0) or 0)
        except Exception:
            content_length = 0  # HEAD unsupported/failed — fall through to GET

        if content_length and content_length > MAX_PDF_BYTES:
            reason = f"{content_length} byte, oltre il limite di {MAX_PDF_BYTES} byte"
            _skip(
                absolute_url,
                f"Allegato PDF ignorato (troppo grande, {reason}): {absolute_url}",
                reason,
                illegible=False,
            )
            continue

        try:
            response = client.get(absolute_url)
            response.raise_for_status()
        except Exception as exc:
            _skip(
                absolute_url,
                f"Allegato PDF non scaricabile: {absolute_url} ({exc})",
                f"download fallito: {exc}",
                illegible=False,
            )
            continue

        if len(response.content) > MAX_PDF_BYTES:
            reason = f"{len(response.content)} byte, oltre il limite di {MAX_PDF_BYTES} byte"
            _skip(
                absolute_url,
                f"Allegato PDF ignorato (troppo grande, {reason}): {absolute_url}",
                reason,
                illegible=False,
            )
            continue

        try:
            import pypdf  # lazy: only pages with a linked PDF pay this cost

            reader = pypdf.PdfReader(io.BytesIO(response.content))
            pages_text = [(p.extract_text() or "") for p in reader.pages]
        except Exception as exc:
            _skip(
                absolute_url,
                f"Allegato PDF illeggibile (parsing fallito): {absolute_url} ({exc})",
                f"parsing fallito: {exc}",
                illegible=True,
            )
            continue

        if not any(t.strip() for t in pages_text):
            reason = "nessun testo estraibile (probabile scansione/immagine)"
            _skip(
                absolute_url,
                f"Allegato PDF ignorato ({reason}): {absolute_url}",
                reason,
                illegible=True,
            )
            continue

        opened += 1
        segments.append({"kind": "allegato", "url": absolute_url, "pages": pages_text})

    return segments, notes, skipped, illegible_count


def build_corpus(
    *,
    body_text: str,
    page_url: str,
    pdf_segments: list[dict[str, Any]],
) -> tuple[str, list[Segment], list[Segment]]:
    """Assemble body + opened-PDF pages into one boundary-tracked corpus.

    Returns `(corpus, boundary_segments, visible_segments)`:
    - `corpus` is the (possibly `MAX_CORPUS_CHARS`-truncated) text to hand
      the extractor.
    - `boundary_segments` is the full, pre-truncation segment list — kept for
      attribution bookkeeping even past the cap.
    - `visible_segments` is `boundary_segments` filtered and sliced down to
      exactly what `corpus` contains, per D-15: a quote cannot legitimately
      be attributed to text the model never read.

    Body always comes first, so a body-only match is attributed to the page
    itself before any PDF segment is even considered — this ordering mirrors
    `wp_pages.py`'s pre-extraction behavior byte-for-byte.
    """
    boundary_segments: list[Segment] = []
    corpus_parts: list[str] = [body_text]
    offset = len(body_text)
    boundary_segments.append(
        Segment(kind="pagina", url=page_url, page_number=None, start=0, text=body_text)
    )
    for seg in pdf_segments:
        header = f"\n\n# Allegato: {seg['url']}\n"
        corpus_parts.append(header)
        offset += len(header)
        for page_index, page_text in enumerate(seg["pages"], start=1):
            if page_index > 1:
                corpus_parts.append("\n")
                offset += 1
            boundary_segments.append(
                Segment(
                    kind="allegato",
                    url=seg["url"],
                    page_number=page_index,
                    start=offset,
                    text=page_text,
                )
            )
            corpus_parts.append(page_text)
            offset += len(page_text)

    corpus = "".join(corpus_parts)
    visible_len = len(corpus)
    if len(corpus) > MAX_CORPUS_CHARS:
        corpus = corpus[:MAX_CORPUS_CHARS]
        visible_len = MAX_CORPUS_CHARS

    # Segments (or the tail of a segment) beyond `visible_len` were never
    # sent to the model — a quote cannot legitimately be attributed to them,
    # cap or not (D-15's MAX_CORPUS_CHARS).
    visible_segments = [
        Segment(
            kind=seg.kind,
            url=seg.url,
            page_number=seg.page_number,
            start=seg.start,
            text=seg.text[: max(0, visible_len - seg.start)],
        )
        for seg in boundary_segments
        if seg.start < visible_len
    ]

    return corpus, boundary_segments, visible_segments
