"""PDF inspection gate before native extraction or OCR.

The inspector is intentionally optional at import time.  When it is absent,
the result is ``unavailable`` and callers must not silently jump to OCR: the
pipeline needs an explicit operational decision and an observable degradation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PdfType(str, Enum):
    TEXT_BASED = "text_based"
    SCANNED = "scanned"
    IMAGE_BASED = "image_based"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class InspectionRoute(str, Enum):
    NATIVE_TEXT = "native_text"
    SELECTIVE_OCR = "selective_ocr"
    FULL_OCR = "full_ocr"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class PdfInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pdf_type: PdfType
    confidence: float = Field(ge=0.0, le=1.0)
    page_count: int = Field(ge=0)
    pages_needing_ocr: tuple[int, ...] = ()
    route: InspectionRoute
    inspector: str = "firecrawl_pdf_inspector"
    error: str | None = None


def inspect_pdf_bytes(
    data: bytes,
    *,
    inspector: Any | None = None,
    confidence_threshold: float = 0.8,
) -> PdfInspection:
    """Classify PDF bytes and choose the next processing route.

    This function only classifies.  It never executes OCR.  The dependency
    injection seam keeps tests and future Rust/CLI backends deterministic.
    """
    if not data:
        return PdfInspection(
            pdf_type=PdfType.UNKNOWN,
            confidence=0.0,
            page_count=0,
            route=InspectionRoute.INVALID,
            error="empty PDF payload",
        )
    if inspector is None:
        try:
            import pdf_inspector as inspector
        except ImportError:
            return PdfInspection(
                pdf_type=PdfType.UNKNOWN,
                confidence=0.0,
                page_count=0,
                route=InspectionRoute.UNAVAILABLE,
                error="pdf-inspector is not installed",
            )
    try:
        result = inspector.classify_pdf_bytes(data)
        pdf_type = _pdf_type(getattr(result, "pdf_type", None))
        confidence = _confidence(getattr(result, "confidence", 0.0))
        page_count = max(0, int(getattr(result, "page_count", 0)))
        pages_needing_ocr = tuple(
            sorted({int(page) for page in getattr(result, "pages_needing_ocr", [])})
        )
    except Exception as exc:  # noqa: BLE001 — inspection is a recorded degradation
        return PdfInspection(
            pdf_type=PdfType.UNKNOWN,
            confidence=0.0,
            page_count=0,
            route=InspectionRoute.INVALID,
            error=f"inspection failed: {exc}",
        )

    if pdf_type is PdfType.TEXT_BASED and confidence >= confidence_threshold:
        route = InspectionRoute.NATIVE_TEXT
    elif pdf_type is PdfType.MIXED and pages_needing_ocr:
        route = InspectionRoute.SELECTIVE_OCR
    elif pdf_type in (PdfType.SCANNED, PdfType.IMAGE_BASED):
        route = InspectionRoute.FULL_OCR
    else:
        route = InspectionRoute.SELECTIVE_OCR if pages_needing_ocr else InspectionRoute.FULL_OCR
    return PdfInspection(
        pdf_type=pdf_type,
        confidence=confidence,
        page_count=page_count,
        pages_needing_ocr=pages_needing_ocr,
        route=route,
    )


def _pdf_type(value: object) -> PdfType:
    try:
        return PdfType(str(value).casefold())
    except ValueError:
        return PdfType.UNKNOWN


def _confidence(value: object) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
