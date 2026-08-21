"""Common check envelope for source identity and connector surfaces."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from treasureiq.catalog.contracts import Surface, _StrictModel
from treasureiq.catalog.recognition import (
    FingerprintEvidence,
    RecognitionAction,
)


class CheckStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    MANUAL_REVIEW = "manual_review"


class CheckResult(_StrictModel):
    """One uniform result for SOURCE_IDENTITY, BASE, AT or SP."""

    source_id: str = Field(min_length=1)
    surface: Surface
    status: CheckStatus
    source_health: bool | None = None
    completeness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    recognition_score: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage_score: float | None = Field(default=None, ge=0.0, le=1.0)
    connector_id: str | None = None
    connector_version: str | None = None
    fingerprint_version: str | None = None
    fingerprint: str | None = None
    identity: dict[str, str | bool | None] = {}
    evidence: tuple[FingerprintEvidence, ...] = ()
    failure_reason: str | None = None
    action: RecognitionAction = RecognitionAction.KEEP
    checked_at: datetime


def source_identity_check(
    *,
    source_id: str,
    declared_url: str,
    response: object | None,
    identity: dict[str, str | bool | None],
    checked_at: datetime,
) -> CheckResult:
    """Build the universal first-level check without performing network I/O."""
    if response is None:
        return CheckResult(
            source_id=source_id,
            surface=Surface.SOURCE_IDENTITY,
            status=CheckStatus.UNAVAILABLE,
            source_health=False,
            identity={**identity, "url_base": declared_url},
            failure_reason="no_http_response",
            action=RecognitionAction.REDISCOVER,
            checked_at=checked_at,
        )
    status_code = getattr(response, "status_code", None)
    final_url = str(getattr(response, "url", "") or "")
    fields = {"url_base": declared_url, "url_finale": final_url or None, **identity}
    present = sum(value not in (None, "", False) for value in fields.values())
    completeness = round(present / len(fields), 6) if fields else 0.0
    healthy = isinstance(status_code, int) and 200 <= status_code < 400
    status = CheckStatus.OK if healthy and completeness >= 0.8 else CheckStatus.DEGRADED
    reason = None if healthy else f"http_{status_code}"
    if status == CheckStatus.DEGRADED and reason is None:
        reason = "identity_incomplete"
    return CheckResult(
        source_id=source_id,
        surface=Surface.SOURCE_IDENTITY,
        status=status,
        source_health=healthy,
        completeness_score=completeness,
        identity={**fields, "http_status": str(status_code)},
        failure_reason=reason,
        action=RecognitionAction.KEEP if status == CheckStatus.OK else RecognitionAction.MANUAL_REVIEW,
        checked_at=checked_at,
    )
