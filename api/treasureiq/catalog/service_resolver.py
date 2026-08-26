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

import os
from datetime import datetime, timezone

from treasureiq.catalog import service_catalog, service_cache
from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.contracts import CAPABILITY_SERVICES, ConnectorRef, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus
from treasureiq.catalog.service_contracts import (
    ResolvedService,
    ServiceKey,
    ServiceReference,
)
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore

#: Provenance stamped on a service served from the promoted flat catalog, so a
#: catalog hit is never mistaken for a live connector call.  ``name="catalog"``
#: marks the versioned national catalog (the originating platform stays on
#: ``reference.provider_platform``); ``version`` tracks the catalog format.
_CATALOG_CONNECTOR = ConnectorRef(name="catalog", version="1")


def _catalogo_flat_attivo() -> bool:
    """Whether the flat-catalog step is enabled (env gate, default OFF).

    The step is wired but inert until ``TREASUREIQ_SERVICE_CATALOG`` is truthy,
    so deploying the code changes no citizen answer until prod flips it on
    deliberately — a reversible switch, not an implicit behaviour change.
    """
    return os.environ.get("TREASUREIQ_SERVICE_CATALOG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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


def resolve_service_with_meta(
    request: DataRequest,
    *,
    mappa: MappaConnettore,
    esito: EsitoConnettore | None = None,
    registry: ConnectorRegistry | None = None,
    platform_id: str = "",
) -> ResolvedService | None:
    """Cache-first resolution into a ``ResolvedService`` envelope (reference + provenance).

    Fresh cache-hit → ``ResolvedService(from_cache=True)`` with the cached
    ``retrieved_at``/``connector`` (no network, connector never called);
    miss/stale → the registered connector, written back through the cache on a
    coherent single-reference success and returned as ``from_cache=False`` with
    the live call timestamp and the ``ConnectorResult``'s connector; anything
    else → ``None`` (never caching a non-result).  An incoherent request (wrong
    surface/capability) is rejected before the cache is even consulted.

    The envelope carries the RESOLUTION timestamp, never ``discovered_at``: the
    batch builder needs when the service was measured, not when its page was
    first found.
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
        return ResolvedService(
            reference=hit.reference,
            retrieved_at=hit.retrieved_at,
            from_cache=True,
            connector=hit.connector,
        )

    # Second tier (``cache fresca → catalogo flat → live``): the promoted national
    # catalog is authoritative-until-next-promotion, so a hit here answers with no
    # network and no write-back — a stored resolution, reported like a cache hit
    # (``from_cache=True`` → FRESH).  ``retrieved_at`` is the promotion/discovery
    # stamp: for a catalog entry there is no separate live resolution event, so
    # ``discovered_at`` IS when it was measured (the deliberate exception to the
    # "never discovered_at" rule that holds for live/cache).  Gated OFF by default.
    if _catalogo_flat_attivo():
        catalog_ref = service_catalog.carica(request.source_id, service_key)
        if catalog_ref is not None:
            return ResolvedService(
                reference=catalog_ref,
                retrieved_at=catalog_ref.discovered_at,
                from_cache=True,
                connector=_CATALOG_CONNECTOR,
            )

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
    # The live-resolution timestamp for freshness: the connector stamps it; fall
    # back to the freshness block, then to now — never to ``discovered_at``.
    retrieved_at = (
        result.retrieved_at
        or result.freshness.retrieved_at
        or datetime.now(timezone.utc)
    )
    # Fix D (Slice 5.2): persist the SAME stamp that goes in the envelope, so a
    # later cache hit replays exactly this instant instead of the write time.
    service_cache.salva(
        request.source_id,
        service_key,
        reference,
        result.connector,
        retrieved_at=retrieved_at,
    )
    return ResolvedService(
        reference=reference,
        retrieved_at=retrieved_at,
        from_cache=False,
        connector=result.connector,
    )


def resolve_service(
    request: DataRequest,
    *,
    mappa: MappaConnettore,
    esito: EsitoConnettore | None,
    registry: ConnectorRegistry | None = None,
    platform_id: str = "",
) -> ServiceReference | None:
    """Cache-first resolution into a ``ServiceReference`` (envelope discarded).

    Thin wrapper over ``resolve_service_with_meta`` for callers that only need
    the reference; the meta variant is the one the Slice 5 chat path uses.
    """
    resolved = resolve_service_with_meta(
        request, mappa=mappa, esito=esito, registry=registry, platform_id=platform_id
    )
    return resolved.reference if resolved is not None else None
