from treasureiq.extract.ocr import OcrScope, build_ocr_plan
from treasureiq.extract.pdf_inspection import (
    InspectionRoute,
    PdfInspection,
    PdfType,
)


def test_mixed_pdf_creates_selective_ocr_plan() -> None:
    plan = build_ocr_plan(
        "doc-1",
        PdfInspection(
            pdf_type=PdfType.MIXED,
            confidence=0.9,
            page_count=4,
            pages_needing_ocr=(2, 4),
            route=InspectionRoute.SELECTIVE_OCR,
        ),
    )

    assert plan is not None
    assert plan.scope is OcrScope.SELECTIVE
    assert plan.pages == (2, 4)


def test_text_pdf_does_not_create_ocr_job() -> None:
    inspection = PdfInspection(
        pdf_type=PdfType.TEXT_BASED,
        confidence=0.99,
        page_count=2,
        route=InspectionRoute.NATIVE_TEXT,
    )

    assert build_ocr_plan("doc-1", inspection) is None
