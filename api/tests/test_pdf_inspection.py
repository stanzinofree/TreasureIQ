from types import SimpleNamespace

from treasureiq.extract.pdf_inspection import (
    InspectionRoute,
    PdfType,
    inspect_pdf_bytes,
)
from treasureiq.extract.pdf_engine import FirecrawlPdfEngine


class _Inspector:
    def __init__(self, result):
        self.result = result

    def classify_pdf_bytes(self, _data: bytes):
        return self.result


def test_text_pdf_routes_to_native_extraction() -> None:
    inspection = inspect_pdf_bytes(
        b"pdf",
        inspector=_Inspector(
            SimpleNamespace(pdf_type="text_based", confidence=0.98, page_count=4, pages_needing_ocr=[])
        ),
    )

    assert inspection.pdf_type is PdfType.TEXT_BASED
    assert inspection.route is InspectionRoute.NATIVE_TEXT
    assert inspection.pages_needing_ocr == ()


def test_mixed_pdf_routes_only_pages_rejected_by_inspector_to_ocr() -> None:
    inspection = inspect_pdf_bytes(
        b"pdf",
        inspector=_Inspector(
            SimpleNamespace(pdf_type="mixed", confidence=0.91, page_count=4, pages_needing_ocr=[2, 4])
        ),
    )

    assert inspection.route is InspectionRoute.SELECTIVE_OCR
    assert inspection.pages_needing_ocr == (2, 4)


def test_missing_inspector_is_explicit_degradation(monkeypatch) -> None:
    monkeypatch.setitem(__import__("sys").modules, "pdf_inspector", None)

    inspection = inspect_pdf_bytes(b"pdf", inspector=None)

    assert inspection.route is InspectionRoute.UNAVAILABLE
    assert inspection.error == "pdf-inspector is not installed"


def test_empty_pdf_is_invalid() -> None:
    inspection = inspect_pdf_bytes(b"")

    assert inspection.route is InspectionRoute.INVALID
    assert inspection.error == "empty PDF payload"


def test_pdf_engine_extracts_native_markdown_only_after_inspection() -> None:
    inspector = _Inspector(
        SimpleNamespace(pdf_type="text_based", confidence=0.99, page_count=1, pages_needing_ocr=[])
    )
    result = FirecrawlPdfEngine(
        inspector=inspector,
        processor=lambda _data: SimpleNamespace(markdown="# Titolo"),
    ).process("doc-1", b"pdf")

    assert result.markdown == "# Titolo"
    assert result.ocr_plan is None


def test_pdf_engine_creates_ocr_plan_without_running_processor() -> None:
    inspector = _Inspector(
        SimpleNamespace(pdf_type="scanned", confidence=0.99, page_count=2, pages_needing_ocr=[])
    )
    result = FirecrawlPdfEngine(
        inspector=inspector,
        processor=lambda _data: (_ for _ in ()).throw(AssertionError("must not run")),
    ).process("doc-2", b"pdf")

    assert result.markdown is None
    assert result.ocr_plan is not None
    assert result.ocr_plan.document_id == "doc-2"
