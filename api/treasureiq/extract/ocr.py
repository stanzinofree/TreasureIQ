"""OCR routing contract, deliberately separate from PDF inspection."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from treasureiq.extract.pdf_inspection import InspectionRoute, PdfInspection


class OcrScope(str, Enum):
    SELECTIVE = "selective"
    FULL = "full"


class OcrPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)
    scope: OcrScope
    pages: tuple[int, ...] = ()
    reason: str = Field(min_length=1)


class OcrPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    markdown: str
    source: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class OcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)
    pages: tuple[OcrPage, ...]
    engine: str = Field(min_length=1)


class OcrEngine(Protocol):
    name: str

    def process(self, data: bytes, plan: OcrPlan) -> OcrResult:
        """Run OCR according to the already decided page scope."""


def build_ocr_plan(document_id: str, inspection: PdfInspection) -> OcrPlan | None:
    """Turn inspection output into an explicit OCR job, without executing it."""
    if inspection.route is InspectionRoute.SELECTIVE_OCR:
        return OcrPlan(
            document_id=document_id,
            scope=OcrScope.SELECTIVE,
            pages=inspection.pages_needing_ocr,
            reason="pdf-inspector ha rifiutato solo alcune pagine",
        )
    if inspection.route is InspectionRoute.FULL_OCR:
        return OcrPlan(
            document_id=document_id,
            scope=OcrScope.FULL,
            reason="pdf-inspector ha classificato il documento come scansione",
        )
    return None
