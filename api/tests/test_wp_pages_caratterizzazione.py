"""Characterization test for `WPPagesConnector`'s PDF + corpus pipeline.

Freezes the observable behavior of `wp_pages.py`'s PDF budget
(`MAX_PDFS_PER_PAGE`, `MAX_PDF_BYTES`), audit trail (`PdfSkip`), corpus
assembly (`Segment` boundaries), and `MAX_CORPUS_CHARS` truncation. The
corpus-assembly logic now lives in `extract/corpus.py` (extracted in
`eaa5184`), which `wp_pages.py` calls into; this test still exercises the
connector end-to-end via `fetch()` — the seam the extraction did NOT move:
budget/audit, recovery ladder, and how the connector hands corpus+segments
to the extractor. The transport is a fake `httpx.MockTransport` — no network
— and the extractor is a `_RecordingExtractor` stand-in that never calls an
LLM: it only records what corpus/segments it was handed.

Golden values here must not change. If a value in this file needs to change
to keep the suite green, a change to `wp_pages.py` / `extract/corpus.py`
altered behavior — fix the code, not the test.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from treasureiq.extract.llm import Segment
from treasureiq.ingest.wp_pages import MAX_CORPUS_CHARS, MAX_PDF_BYTES, WPPagesConnector
from treasureiq.schema import RecoveryLevel

FIXTURES = Path(__file__).parent / "fixtures"
REAL_PDF_BYTES = (FIXTURES / "bando_caratterizzazione.pdf").read_bytes()
ILLEGIBLE_PDF_BYTES = b"questo non e' un PDF valido, solo byte a caso senza header"

BASE_URL = "http://comune-caratterizzazione.example"

#: Body padded well past MAX_CORPUS_CHARS on its own, so the page-body
#: segment alone forces truncation before any PDF segment is ever visible
#: to the model — the scenario D-15's MAX_CORPUS_CHARS cap exists for.
_FILLER = (
    "Requisito di ammissibilita': ISEE, residenza, beneficiari, anni di eta'. "
)
_LONG_PARAGRAPH = _FILLER * (1 + (MAX_CORPUS_CHARS * 2) // len(_FILLER))

BODY_HTML = (
    f"<p>{_LONG_PARAGRAPH}</p>"
    '<p><a href="/files/good.pdf">Bando (PDF)</a></p>'
    '<p><a href="/files/oversized.pdf">Allegato grande (PDF)</a></p>'
    '<p><a href="/files/illegible.pdf">Allegato illeggibile (PDF)</a></p>'
)

PAGE_RECORD = {
    "id": 42,
    "title": {"rendered": "Bando di prova per la caratterizzazione"},
    "content": {"rendered": BODY_HTML},
    "link": f"{BASE_URL}/bando-di-prova/",
    "date": "2026-01-15T10:00:00",
}

OVERSIZED_CONTENT_LENGTH = MAX_PDF_BYTES + 5_000


class _RecordingExtractor:
    """Stands in for `RequirementsExtractor`: records the corpus it was
    handed and always declines (`extract()` returns `None`), so the test
    never depends on LLM behavior — only on what `wp_pages.py` builds and
    hands to the extractor, which is exactly the code being moved to
    `extract/corpus.py`."""

    available = True

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def extract(
        self,
        *,
        text: str,
        title: str,
        raw_hash: str,
        visible_segments: list[Segment],
        full_segments: list[Segment],
    ) -> None:
        self.calls.append(
            {
                "text": text,
                "title": title,
                "raw_hash": raw_hash,
                "visible_segments": visible_segments,
                "full_segments": full_segments,
            }
        )
        return None


class _DeterministicPdfInspector:
    """Injected PDF-inspection backend so the recovery-ladder assertions never
    depend on the installed `pdf_inspector` package's heuristic or version.

    Real PDF bytes (`%PDF` header) classify as TEXT_BASED with high confidence
    -> `inspect_pdf_bytes` routes NATIVE_TEXT -> the attachment opens via pypdf.
    Anything else raises, which `inspect_pdf_bytes` records as an INVALID
    (illegible) skip. These are exactly the two routes this characterization
    pins: `good.pdf` opens, `illegible.pdf` is unreadable — neither is left to
    the live inspector's judgement, which drifts across package versions."""

    class _Result:
        pdf_type = "text_based"
        confidence = 0.99
        page_count = 1
        pages_needing_ocr: tuple[int, ...] = ()

    def classify_pdf_bytes(self, data: bytes) -> "_DeterministicPdfInspector._Result":
        if data.startswith(b"%PDF"):
            return self._Result()
        raise ValueError("Not a PDF: file appears to be plain text")


def _transport_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)

    if "/wp-json/wp/v2/pages" in url:
        params = dict(request.url.params)
        if params.get("search") == "bando":
            return httpx.Response(200, json=[PAGE_RECORD])
        return httpx.Response(200, json=[])

    if url.endswith("/files/good.pdf"):
        if request.method == "HEAD":
            return httpx.Response(
                200, headers={"content-length": str(len(REAL_PDF_BYTES))}
            )
        return httpx.Response(200, content=REAL_PDF_BYTES)

    if url.endswith("/files/oversized.pdf"):
        if request.method == "HEAD":
            return httpx.Response(
                200, headers={"content-length": str(OVERSIZED_CONTENT_LENGTH)}
            )
        raise AssertionError(
            "oversized.pdf must be skipped from the HEAD content-length "
            "alone; a GET here means the size budget check regressed"
        )

    if url.endswith("/files/illegible.pdf"):
        if request.method == "HEAD":
            return httpx.Response(
                200, headers={"content-length": str(len(ILLEGIBLE_PDF_BYTES))}
            )
        return httpx.Response(200, content=ILLEGIBLE_PDF_BYTES)

    raise AssertionError(f"unexpected request in characterization test: {request.method} {url}")


@pytest.fixture
def connector() -> WPPagesConnector:
    extractor = _RecordingExtractor()
    conn = WPPagesConnector(
        base_url=BASE_URL,
        ente="Comune di Caratterizzazione",
        codice_istat="999999",
        extractor=extractor,  # type: ignore[arg-type]
        pdf_inspector=_DeterministicPdfInspector(),
        max_pages=50,
    )
    conn._client = httpx.Client(
        transport=httpx.MockTransport(_transport_handler),
        headers={"User-Agent": "test-caratterizzazione"},
    )
    conn._extractor_recorder = extractor  # type: ignore[attr-defined]
    return conn


def test_pdf_budget_and_audit_trail(connector: WPPagesConnector) -> None:
    """PDF budget (D-08/A6): one opens, one is too large, one is unreadable —
    every skip is audited with a human-readable reason and a `PdfSkip`."""
    opportunities = connector.fetch()
    assert len(opportunities) == 1
    opp = opportunities[0]

    assert opp.pdfs_linked == 3
    assert opp.pdfs_opened == 1
    assert len(opp.pdfs_skipped) == 2

    skipped_by_url = {skip.url: skip for skip in opp.pdfs_skipped}
    oversized_skip = skipped_by_url[f"{BASE_URL}/files/oversized.pdf"]
    illegible_skip = skipped_by_url[f"{BASE_URL}/files/illegible.pdf"]

    assert "oltre il limite di" in oversized_skip.reason
    assert str(MAX_PDF_BYTES) in oversized_skip.reason
    # illegible.pdf is plain-text bytes: the inspection gate rejects it as an
    # INVALID PDF before pypdf is ever reached. Still an audited illegible skip
    # (counts toward L3), only caught one stage earlier than a pypdf parse
    # failure — the characterization pins "unreadable & audited", not the stage.
    assert "Not a PDF" in illegible_skip.reason

    assert any(
        "Allegato PDF ignorato (troppo grande" in note for note in opp.extraction_notes
    )
    assert any(
        "Allegato PDF illeggibile (ispezione fallita)" in note
        for note in opp.extraction_notes
    )


def test_corpus_truncation_and_segment_boundaries(connector: WPPagesConnector) -> None:
    """MAX_CORPUS_CHARS truncation (D-15): the body alone already exceeds the
    cap, so the model sees only (a truncated) body — the PDF segment's
    `start` falls beyond `visible_len` and is excluded from what is sent to
    the extractor, though it is still present in `full_segments` for
    attribution bookkeeping."""
    opportunities = connector.fetch()
    opp = opportunities[0]

    extractor = connector._extractor_recorder  # type: ignore[attr-defined]
    assert len(extractor.calls) == 1
    call = extractor.calls[0]

    assert opp.chars_processed == MAX_CORPUS_CHARS
    assert call["text"] == call["text"][:MAX_CORPUS_CHARS]
    assert len(call["text"]) == MAX_CORPUS_CHARS

    visible_segments: list[Segment] = call["visible_segments"]  # type: ignore[assignment]
    full_segments: list[Segment] = call["full_segments"]  # type: ignore[assignment]

    # Full (pre-truncation) boundary list: page body + the one opened PDF's
    # single page — oversized/illegible attachments never became segments.
    assert len(full_segments) == 2
    assert full_segments[0].kind == "pagina"
    assert full_segments[0].start == 0
    assert full_segments[1].kind == "allegato"
    assert full_segments[1].url == f"{BASE_URL}/files/good.pdf"
    assert full_segments[1].page_number == 1
    assert full_segments[1].start > MAX_CORPUS_CHARS  # body alone already over cap

    # Visible (post-truncation) list: only the body segment survives, and it
    # is sliced down to exactly what the model saw.
    assert len(visible_segments) == 1
    assert visible_segments[0].kind == "pagina"
    assert visible_segments[0].start == 0
    assert len(visible_segments[0].text) == MAX_CORPUS_CHARS


def test_recovery_level_and_notes(connector: WPPagesConnector) -> None:
    """D-16 ladder: no requirement survived (extractor always declines) but a
    PDF genuinely opened, so this is L1_manuale — not L3 (that rung is
    reserved for "every linked PDF failed to open"), and not L2 (nothing was
    quote-gated)."""
    opportunities = connector.fetch()
    opp = opportunities[0]

    assert opp.recovery_level == RecoveryLevel.L1_MANUALE
    assert opp.requirements_recovered is None
    assert opp.requirements.is_empty
    assert any(
        "Estrazione non eseguita (nessuna cache disponibile" in note
        for note in opp.extraction_notes
    )
    assert opp.extraction_seconds >= 0.0


def test_no_selection_drops_and_stats(connector: WPPagesConnector) -> None:
    """The single fixture page carries an eligibility signal, so the content
    filter (`_select_pages`) keeps it — nothing dropped, one record seen and
    emitted."""
    opportunities = connector.fetch()
    assert len(opportunities) == 1
    assert connector.dropped == []
    assert connector.stats.records_seen == 1
    assert connector.stats.records_emitted == 1
