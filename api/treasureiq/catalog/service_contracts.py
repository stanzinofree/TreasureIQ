"""Contracts for municipal online services and authenticated portals.

The institutional site remains the discovery surface for a service, but the
service itself has a separate contract.  This keeps a downloadable form,
instructions and an authenticated procedure as distinct access options
without pretending that TIQ can perform a citizen's authentication.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import AnyHttpUrl, Field

from treasureiq.catalog.contracts import Surface, _StrictModel


class ServiceKey(str, Enum):
    """Closed vocabulary of civic services the chat can request (Ramo 3).

    A normalized identity for the service the citizen asks about — distinct
    from any portal entrypoint (``ServicePortalCandidate``) or access mode.
    It is a domain contract shared by chat recognition, the query planner and
    the (future) service cache/connectors, so it lives here and not in
    ``chat/`` (chat recognises the key, it does not own the vocabulary).

    Extended only by adding a value, never by falling back on the nearest
    one: a service outside this vocabulary stays unrecognised (``None`` at the
    recogniser), it is not mapped to a neighbour.
    """

    CARTA_IDENTITA = "carta_identita"
    CAMBIO_RESIDENZA = "cambio_residenza"
    ACCESSO_ATTI = "accesso_atti"
    STATO_CIVILE = "stato_civile"
    TRIBUTI = "tributi"


class ServiceAccessMode(str, Enum):
    INFORMATION = "information"
    DOWNLOAD = "download"
    AUTHENTICATED_ONLINE = "authenticated_online"


class AuthenticationMethod(str, Enum):
    SPID = "spid"
    CIE = "cie"
    CNS = "cns"
    PASSWORD = "password"
    UNKNOWN = "unknown"


class ServicePortalRole(str, Enum):
    PERSONAL_AREA = "personal_area"
    APPOINTMENT = "appointment"
    TELEMATICS_DESK = "telematics_desk"
    ONLINE_SERVICE = "online_service"
    UNKNOWN = "unknown"


class ServiceAccessOption(_StrictModel):
    """One official way to reach a service discovered by a connector."""

    mode: ServiceAccessMode
    url: AnyHttpUrl
    provider: str | None = None
    authentication: tuple[AuthenticationMethod, ...] = ()
    requires_authentication: bool = False
    official: bool = True
    source_url: AnyHttpUrl | None = None
    automatable: bool = False


class ServiceReference(_StrictModel):
    """A normalized service reference emitted by BASE discovery.

    ``options`` can contain both a public/download path and an authenticated
    online path for the same service.  The query planner later chooses the
    requested path; it never infers credentials or logs in.
    """

    service_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: AnyHttpUrl
    options: tuple[ServiceAccessOption, ...] = Field(min_length=1)
    discovered_from: Surface = Surface.ORDINARY_DATA
    provider_platform: str | None = None
    discovered_at: datetime


#: Bump when WHAT we normalise into a cached ``ServiceReference`` changes, so an
#: entry written by an older (or newer) extractor is never served as-is.  The
#: cache treats any ``schema_version`` other than this as a miss (re-resolve).
SERVICE_CACHE_SCHEMA_VERSION = 1


class CachedService(_StrictModel):
    """One entry of the resolved-service cache, keyed by ``service_key``.

    ``reference`` is the normalised service; ``retrieved_at`` is when the
    connector RESOLVED it, distinct from ``reference.discovered_at`` (when the
    entrypoint/service was first DISCOVERED).  ``schema_version`` gates the
    entry: a value other than ``SERVICE_CACHE_SCHEMA_VERSION`` is a miss.
    """

    service_key: ServiceKey
    reference: ServiceReference
    retrieved_at: datetime
    schema_version: int = Field(default=SERVICE_CACHE_SCHEMA_VERSION, ge=0)


class ServiceCacheFile(_StrictModel):
    """The per-municipality cache file: several ``service_key`` entries coexist."""

    source_id: str = Field(min_length=1)
    entries: tuple[CachedService, ...] = ()
    updated_at: datetime


class ServicePortalCandidate(_StrictModel):
    """A persisted SP entrypoint found on the official BASE site.

    ``url`` is deliberately the URL used by confirmation checks.  Discovery
    metadata remains alongside it so a broken entrypoint can trigger a new
    discovery without confusing the last known portal with a guessed URL.
    """

    url: AnyHttpUrl
    label: str = Field(min_length=1)
    source_url: AnyHttpUrl
    role: ServicePortalRole = ServicePortalRole.UNKNOWN
    access_mode: ServiceAccessMode = ServiceAccessMode.AUTHENTICATED_ONLINE
    provider_hint: str | None = None
    platform_id: str | None = None
    fingerprint: str | None = None
    recognition_status: str = "unknown"
    capabilities: tuple[str, ...] = ()
    authentication: tuple[AuthenticationMethod, ...] = ()
    discovered_at: datetime


class ServicePortalGroup(_StrictModel):
    """Logical SP portal grouping one platform and its capabilities."""

    portal_id: str = Field(min_length=1)
    platform_id: str | None = None
    entrypoints: tuple[AnyHttpUrl, ...] = Field(min_length=1)
    roles: tuple[ServicePortalRole, ...] = ()
    capabilities: tuple[str, ...] = ()
    recognition_status: str = "unknown"


class SourceInventory(_StrictModel):
    """Persistent inventory of source entrypoints for a municipality.

    ``transparency_url`` is the persisted AT entrypoint (not merely the page
    where discovery started); each ``service_portals[].url`` is an SP
    entrypoint.  Confirmation checks must start from these URLs and never
    rediscover the institutional home unless confirmation fails.
    """

    source_id: str = Field(min_length=1)
    base_url: AnyHttpUrl
    base_platform: str | None = None
    base_fingerprint: str | None = None
    base_confirmed_at: datetime | None = None
    base_source_health: bool | None = None
    base_failure_reason: str | None = None
    transparency_url: AnyHttpUrl | None = None
    transparency_platform: str | None = None
    transparency_fingerprint: str | None = None
    transparency_confirmed_at: datetime | None = None
    service_portals: tuple[ServicePortalCandidate, ...] = ()
    service_portal_groups: tuple[ServicePortalGroup, ...] = ()
    updated_at: datetime
