"""Versioned recognition contracts for BASE, AT and SERVICE_PORTAL.

Recognition is evidence about a source, not a verdict about the municipality.
The contracts here make connector changes observable and make the next action
(keep, confirm, rediscover or manual review) deterministic.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from treasureiq.catalog.contracts import Surface, _StrictModel


class RecognitionConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class RecognitionAction(str, Enum):
    KEEP = "keep"
    CONFIRM = "confirm"
    REDISCOVER = "rediscover"
    MANUAL_REVIEW = "manual_review"


class FingerprintEvidence(_StrictModel):
    """One weighted observation used by a connector fingerprint."""

    key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    matched: bool
    weight: float = Field(ge=0.0, le=1.0)
    observed: str | None = None
    expected: str | None = None


class ResweepPolicy(_StrictModel):
    """Policy for translating connector/fingerprint changes into work."""

    minimum_score: float = Field(default=0.80, ge=0.0, le=1.0)
    manual_review_below: float = Field(default=0.60, ge=0.0, le=1.0)
    fingerprint_change: RecognitionAction = RecognitionAction.REDISCOVER
    connector_patch: RecognitionAction = RecognitionAction.CONFIRM
    connector_minor: RecognitionAction = RecognitionAction.CONFIRM
    connector_major: RecognitionAction = RecognitionAction.REDISCOVER


class ConnectorVersionManifest(_StrictModel):
    """Immutable identity and recognition policy of one connector release."""

    connector_id: str = Field(min_length=1)
    version: str = Field(min_length=1, pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    contract_version: str = Field(min_length=1)
    fingerprint_version: str = Field(min_length=1)
    surfaces: tuple[Surface, ...] = Field(min_length=1)
    platforms: tuple[str, ...] = ("*",)
    policy: ResweepPolicy = ResweepPolicy()


class RecognitionResult(_StrictModel):
    """Recognition outcome persisted for one source surface."""

    source_id: str = Field(min_length=1)
    surface: Surface
    platform_id: str | None = None
    connector_id: str = Field(min_length=1)
    connector_version: str = Field(min_length=1)
    fingerprint_version: str = Field(min_length=1)
    fingerprint: str | None = None
    recognition_score: float = Field(ge=0.0, le=1.0)
    coverage_score: float | None = Field(default=None, ge=0.0, le=1.0)
    source_health: bool | None = None
    failure_reason: str | None = None
    confidence: RecognitionConfidence = RecognitionConfidence.UNKNOWN
    evidence: tuple[FingerprintEvidence, ...] = ()
    checked_at: datetime
    action: RecognitionAction = RecognitionAction.KEEP


def score_evidence(evidence: tuple[FingerprintEvidence, ...]) -> float:
    """Return the weighted fingerprint score, rounded for stable persistence."""
    total = sum(item.weight for item in evidence)
    if total == 0:
        return 0.0
    matched = sum(item.weight for item in evidence if item.matched)
    return round(matched / total, 6)


def action_for_recognition(
    *,
    score: float,
    policy: ResweepPolicy,
    fingerprint_changed: bool = False,
    connector_major_changed: bool = False,
    connector_minor_changed: bool = False,
) -> RecognitionAction:
    """Choose the next operation without consulting an LLM."""
    if score < policy.manual_review_below:
        return RecognitionAction.MANUAL_REVIEW
    if connector_major_changed:
        return policy.connector_major
    if fingerprint_changed:
        return policy.fingerprint_change
    if connector_minor_changed:
        return policy.connector_minor
    if score < policy.minimum_score:
        return RecognitionAction.REDISCOVER
    return RecognitionAction.KEEP
