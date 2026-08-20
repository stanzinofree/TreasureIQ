"""Strict internal contracts between query planner, adapters, and chat."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from treasureiq.catalog.contracts import AccessMode, FreshnessStatus, Surface


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataStatus(str, Enum):
    FULFILLED = "fulfilled"
    EMPTY = "empty"
    NOT_SUPPORTED = "not_supported"
    NOT_FOUND = "not_found"
    STALE = "stale"
    UNREADABLE = "unreadable"
    FAILED = "failed"


class FreshnessPolicy(_StrictModel):
    max_age_seconds: int = Field(ge=0)
    allow_live: bool = True


class RequestLimits(_StrictModel):
    max_records: int = Field(default=100, ge=0)
    max_documents: int = Field(default=10, ge=0)
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=0)


class DataRequest(_StrictModel):
    request_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    surface: Surface
    capability: str = Field(min_length=1)
    selection: dict[str, Any] = {}
    filters: dict[str, Any] = {}
    freshness: FreshnessPolicy
    limits: RequestLimits = RequestLimits()
    manifest_revision: int = Field(ge=0)


class Freshness(_StrictModel):
    status: FreshnessStatus
    retrieved_at: datetime | None = None
    source_age_seconds: int | None = Field(default=None, ge=0)


class EvidenceRef(_StrictModel):
    evidence_id: str = Field(min_length=1)
    field: str = Field(min_length=1)


class TransportMeta(_StrictModel):
    requests: int = Field(default=0, ge=0)
    bytes: int = Field(default=0, ge=0)
    from_cache: bool = False


class ConnectorRef(_StrictModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class DataBatch(_StrictModel):
    request_id: str = Field(min_length=1)
    status: DataStatus
    access_mode: AccessMode
    source_id: str = Field(min_length=1)
    surface: Surface
    capability: str = Field(min_length=1)
    records: tuple[dict[str, Any], ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    freshness: Freshness
    limitations: tuple[str, ...] = ()
    transport: TransportMeta = TransportMeta()
    connector: ConnectorRef
