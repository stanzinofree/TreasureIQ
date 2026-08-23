"""Stable seam for BASE/AT/SP recognition plugins."""

from __future__ import annotations

from typing import Protocol

from pydantic import AnyHttpUrl, Field

from treasureiq.catalog.contracts import Surface, _StrictModel
from treasureiq.catalog.recognition import FingerprintEvidence, RecognitionConfidence


class RecognitionObservation(_StrictModel):
    """Immutable HTTP observation prepared by the core for one entrypoint."""

    source_id: str = Field(min_length=1)
    surface: Surface
    entrypoint_url: AnyHttpUrl
    final_url: AnyHttpUrl | None = None
    http_status: int | None = None
    headers: dict[str, str] = {}
    body: str = ""
    base_platform_hint: str | None = None
    expected_platform: str | None = None
    metadata: dict[str, str | None] = {}


class RecognitionPluginManifest(_StrictModel):
    """Versioned identity and scope of one recognition plugin."""

    plugin_id: str = Field(min_length=1)
    version: str = Field(min_length=1, pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    contract_version: str = Field(min_length=1)
    fingerprint_version: str = Field(min_length=1)
    surface: Surface
    platforms: tuple[str, ...] = ("*",)


class RecognitionPluginResult(_StrictModel):
    """Plugin output before the core applies action policy and persistence."""

    platform_id: str | None = None
    recognition_score: float = Field(ge=0.0, le=1.0)
    confidence: RecognitionConfidence = RecognitionConfidence.UNKNOWN
    fingerprint: str | None = None
    evidence: tuple[FingerprintEvidence, ...] = ()


class RecognitionPlugin(Protocol):
    manifest: RecognitionPluginManifest

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        """Recognize one already-fetched response without network I/O."""
