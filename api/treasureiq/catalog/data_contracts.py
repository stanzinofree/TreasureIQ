"""Strict internal contracts between query planner, adapters, and chat."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from treasureiq.catalog.contracts import AccessMode, ConnectorRef, FreshnessStatus, Surface
from treasureiq.catalog.service_contracts import ServiceReference

# ``ConnectorRef`` moved to ``contracts`` to break an import cycle (service
# contracts now reference it); re-exported here for its historical callers.
__all__ = ["ConnectorRef"]  # not exhaustive: only the moved symbol, for clarity


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
    #: ≥2 servizi confermati per la stessa ServiceKey: nessuno è "quello giusto"
    #: da eleggere (il gate exactly-one rifiuta), ma i candidati sono validi e
    #: vanno esposti come SCELTA al cittadino. Distinto da NOT_FOUND (0 = miss
    #: onesto) e da FULFILLED (1 = risoluzione singola). Non promuovibile né
    #: cacheabile: è una lista di riferimenti del turno, non un dato risolto.
    DISAMBIGUATION = "disambiguation"


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
    allowed_modes: tuple[AccessMode, ...] = (
        AccessMode.DIRECT,
        AccessMode.MEDIATED,
        AccessMode.INDIRECT,
    )
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


class DataBatch(_StrictModel):
    request_id: str = Field(min_length=1)
    status: DataStatus
    access_mode: AccessMode
    source_id: str = Field(min_length=1)
    surface: Surface
    capability: str = Field(min_length=1)
    records: tuple[dict[str, Any], ...] = ()
    service_references: tuple[ServiceReference, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    freshness: Freshness
    limitations: tuple[str, ...] = ()
    transport: TransportMeta = TransportMeta()
    connector: ConnectorRef
