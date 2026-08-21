"""Strict shared vocabulary for the v1 backoffice catalog."""

from __future__ import annotations

from enum import Enum

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Surface(str, Enum):
    SOURCE_IDENTITY = "source_identity"
    ORDINARY_DATA = "ordinary_data"
    TRANSPARENCY = "transparency"
    SERVICE_PORTAL = "service_portal"


class AccessMode(str, Enum):
    DIRECT = "direct"
    MEDIATED = "mediated"
    INDIRECT = "indirect"
    UNAVAILABLE = "unavailable"


class AgidCompatibility(str, Enum):
    COMPATIBLE = "compatible"
    PARTIAL = "partial"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class SectionStatus(str, Enum):
    ABSENT = "absent"
    PRESENT_EMPTY = "present_empty"
    PRESENT = "present"
    PARTIALLY_RECOVERED = "partially_recovered"
    UNREADABLE = "unreadable"
    UNKNOWN = "unknown"


class CapabilityStatus(str, Enum):
    VERIFIED = "verified"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    STALE = "stale"
    BROKEN = "broken"


class FreshnessStatus(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    LIVE = "live"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class AccessContract(_StrictModel):
    transport: str = Field(min_length=1)
    endpoints: tuple[str, ...] = ()
    authentication: str = Field(min_length=1)
    pagination: str | None = None
    schema_version: str | None = None


class ConnectorContract(_StrictModel):
    adapter: str = Field(min_length=1)
    mode: AccessMode
    version: str = Field(min_length=1)


class SourceRef(_StrictModel):
    source_id: str = Field(min_length=1)
    base_url: AnyHttpUrl | None = None
