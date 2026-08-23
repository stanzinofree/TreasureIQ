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


#: Vocabolario dei bandi, tenuto esplicito e centralizzato (Ramo 2): la
#: capability del contratto utente e la sezione amministrativa del catalogo sono
#: due cose diverse e non vanno confuse in una stringa duplicata.
#:  - `CAPABILITY_NOTICES` è la capability del contratto chat/DataBatch (planner,
#:    proiezione `notices`): ciò che il cittadino chiede.
#:  - `CATALOG_SECTION_PUBLIC_NOTICES` è la sezione del catalogo amministrativo
#:    (sweep/shadow), già presente: ciò che il backoffice censisce.
#: Restano distinte di proposito — il vocabolario amministrativo non deve
#: contaminare il contratto utente.
CAPABILITY_NOTICES = "notices"
CATALOG_SECTION_PUBLIC_NOTICES = "public_notices"


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
