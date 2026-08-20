"""Deterministic PDF acquisition pipeline: inspect, then extract or plan OCR."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict

from treasureiq.extract.ocr import OcrPlan, build_ocr_plan
from treasureiq.extract.pdf_inspection import (
    InspectionRoute,
    PdfInspection,
    inspect_pdf_bytes,
)


class PdfExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inspection: PdfInspection
    markdown: str | None = None
    ocr_plan: OcrPlan | None = None
    error: str | None = None


class FirecrawlPdfEngine:
    """Use pdf-inspector as the gate before native Markdown extraction."""

    def __init__(
        self,
        *,
        inspector: Any | None = None,
        processor: Callable[[bytes], Any] | None = None,
        confidence_threshold: float = 0.8,
    ) -> None:
        self.inspector = inspector
        self.processor = processor
        self.confidence_threshold = confidence_threshold

    def process(self, document_id: str, data: bytes) -> PdfExtractionResult:
        inspection = inspect_pdf_bytes(
            data,
            inspector=self.inspector,
            confidence_threshold=self.confidence_threshold,
        )
        if inspection.route is not InspectionRoute.NATIVE_TEXT:
            return PdfExtractionResult(
                inspection=inspection,
                ocr_plan=build_ocr_plan(document_id, inspection),
                error=inspection.error,
            )

        processor = self.processor
        if processor is None:
            try:
                import pdf_inspector

                processor = pdf_inspector.process_pdf_bytes
            except (ImportError, AttributeError) as exc:
                return PdfExtractionResult(
                    inspection=inspection,
                    error=f"native PDF extraction unavailable: {exc}",
                )
        try:
            result = processor(data)
            markdown = getattr(result, "markdown", None)
            if not isinstance(markdown, str) or not markdown.strip():
                return PdfExtractionResult(
                    inspection=inspection,
                    error="native PDF extraction returned no Markdown",
                )
            return PdfExtractionResult(inspection=inspection, markdown=markdown)
        except Exception as exc:  # noqa: BLE001 — preserve a recorded degradation
            return PdfExtractionResult(
                inspection=inspection,
                error=f"native PDF extraction failed: {exc}",
            )
