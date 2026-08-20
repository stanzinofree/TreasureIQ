from types import SimpleNamespace

from treasureiq.extract.pdf_inspection import (
    InspectionRoute,
    PdfType,
    inspect_pdf_bytes,
)


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
