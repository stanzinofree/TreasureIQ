"""Resolve a recognised ``ServiceKey`` into a ``ServiceReference`` (Ramo 3, Slice 3).

The orchestration seam between the resolved-service cache (Slice 2, store only)
and the service connectors (Slice 4, real platforms).  Cache-first: a fresh hit
answers with no network; a miss/stale runs a connector and writes the result
back through the cache.  This module never chooses language, profile or theme —
the ``ServiceKey`` arrives already recognised inside the ``DataRequest`` (Slice
1); the resolver only routes and gates.

It is distinct from ``ServicePortalConnettore``: that surfaces a discovered SP
entrypoint (``SERVICE_PORTAL``/``INDIRECT``) as an honest pointer, this resolves
an ordinary-data service (``ORDINARY_DATA``/``CAPABILITY_SERVICES``) into a
normalised ``ServiceReference``.  The guards below keep the two from crossing.

No network here: the connector registry is empty until Slice 4 wires a pilot.
"""

from __future__ import annotations

from treasureiq.catalog import service_cache
from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus
from treasureiq.catalog.service_contracts import ServiceKey, ServiceReference
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore


def _service_key_da_selezione(request: DataRequest) -> ServiceKey | None:
    """The requested ``ServiceKey``, or ``None`` if absent/outside vocabulary.

    Deterministic like the recogniser: an unknown value maps to ``None``, never
    to the nearest key.
    """
    raw = request.selection.get("service_key")
    if not raw:
        return None
    try:
        return ServiceKey(raw)
    except ValueError:
        return None


def resolve_service(
    request: DataRequest,
    *,
    mappa: MappaConnettore,
    esito: EsitoConnettore | None,
    registry: ConnectorRegistry | None = None,
    platform_id: str = "",
) -> ServiceReference | None:
    """Cache-first resolution of a service request into a ``ServiceReference``.

    Fresh cache-hit → the cached reference (no network, connector never called);
    miss/stale → the registered connector, written back through the cache on a
    coherent single-reference success; anything else → ``None`` (never caching a
    non-result).  An incoherent request (wrong surface/capability) is rejected
    before the cache is even consulted.
    """
    # Guard 1 (before the cache): reject an incoherent request outright so it can
    # never find a cached entry and bypass the connector's own supports() gate.
    if request.surface is not Surface.ORDINARY_DATA:
        raise ValueError(
            f"resolve_service richiede Surface.ORDINARY_DATA, non {request.surface}"
        )
    if request.capability != CAPABILITY_SERVICES:
        raise ValueError(
            f"resolve_service richiede capability {CAPABILITY_SERVICES!r}, "
            f"non {request.capability!r}"
        )

    service_key = _service_key_da_selezione(request)
    if service_key is None:
        return None

    hit = service_cache.carica(request.source_id, service_key, policy=request.freshness)
    if hit is not None:
        return hit

    registry = registry or ConnectorRegistry()
    connector = registry.resolve(request=request, platform_id=platform_id)
    if connector is None:
        return None

    result = connector.retrieve(request, mappa=mappa, esito=esito)

    # Guard 2: exactly one reference. Zero is a miss; more than one demands an
    # explicit decision at a higher level, never an implicit pick here.
    if result.status is not DataStatus.FULFILLED:
        return None
    if len(result.service_references) != 1:
        return None

    # Guard 3: the result must be about THIS request/source, or it must not land
    # in the correct municipality's cache.
    if result.source_id != request.source_id or result.request_id != request.request_id:
        return None

    reference = result.service_references[0]
    service_cache.salva(request.source_id, service_key, reference)
    return reference
