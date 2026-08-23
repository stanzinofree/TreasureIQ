"""SERVICE_PORTAL executor: point to the official portal, never authenticate.

These tests pin the seam wired in slice 3E (additive, no chat caller yet):

* a discovered service resolves through CatalogRuntime to an INDIRECT batch
  carrying a credential-free pointer (URL + accepted auth methods);
* an unknown ``service_id`` or a missing inventory collapses to NOT_FOUND with
  no records — TIQ never guesses a portal URL;
* the connector and adapter resolve for the SERVICE_PORTAL surface and win over
  the wildcard scrape fallback (which does not claim that surface).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from treasureiq.catalog.adapters.defaults import default_adapter_registry
from treasureiq.catalog.connector_defaults import default_connector_registry
from treasureiq.catalog.contracts import AccessMode, Surface
from treasureiq.catalog.data_contracts import DataStatus
from treasureiq.catalog.flotta import flotta_connectors
from treasureiq.catalog.planner import service_portal_request
from treasureiq.catalog.runtime import CatalogRuntime
from treasureiq.catalog.service_contracts import (
    AuthenticationMethod,
    ServiceAccessMode,
    ServicePortalCandidate,
    ServicePortalRole,
    SourceInventory,
)
from treasureiq.catalog.service_portal_connector import ServicePortalConnettore
from treasureiq.mappa_connettore import MappaConnettore

ISTAT = "058091"
WHEN = datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc)
PORTAL_URL = "https://sportello.comune.prova.it/servizi"
BASE_URL = "https://www.comune.prova.it"


def _mappa() -> MappaConnettore:
    return MappaConnettore(
        codice_istat=ISTAT,
        nome="Comune di Prova",
        sito=BASE_URL,
        sondato_il=WHEN.isoformat(),
    )


def _inventory() -> SourceInventory:
    return SourceInventory(
        source_id=ISTAT,
        base_url=BASE_URL,
        service_portals=(
            ServicePortalCandidate(
                url=PORTAL_URL,
                label="Sportello telematico",
                source_url=BASE_URL,
                role=ServicePortalRole.TELEMATICS_DESK,
                access_mode=ServiceAccessMode.AUTHENTICATED_ONLINE,
                platform_id="municipium",
                capabilities=("appointment",),
                authentication=(AuthenticationMethod.SPID, AuthenticationMethod.CIE),
                discovered_at=WHEN,
            ),
        ),
        updated_at=WHEN,
    )


def _runtime(inventory: SourceInventory | None) -> CatalogRuntime:
    connector = ServicePortalConnettore(inventory_loader=lambda source_id: inventory)
    registry = default_connector_registry()
    # Swap the disk-backed default for the injected loader without touching order.
    registry._connectors["service_portal"] = connector  # noqa: SLF001 — test seam
    return CatalogRuntime(connectors=registry, adapters=default_adapter_registry())


def _request(service_id: str = PORTAL_URL):
    return service_portal_request(source_id=ISTAT, service_id=service_id)


# ── Resolution: SP connector/adapter win for the SERVICE_PORTAL surface ──────

def test_service_portal_connector_resolves_for_its_surface():
    registry = default_connector_registry()
    connector = registry.resolve(request=_request(), platform_id="municipium")
    assert connector is not None
    assert connector.name == "service_portal"
    assert connector.name not in {c.name for c in flotta_connectors()}


def test_service_portal_is_never_a_scrape_fallback():
    # SP needs an explicit service_id; it must never be picked as the wildcard
    # indirect fallback for an unknown platform (web_scrape owns that route).
    from treasureiq.catalog.data_contracts import FreshnessPolicy, RequestLimits

    requests = default_adapter_registry().fallback_requests_for(
        source_id=ISTAT,
        platform_id="piattaforma-sconosciuta",
        request_prefix="fallback",
        freshness=FreshnessPolicy(max_age_seconds=86400),
        limits=RequestLimits(),
        manifest_revision=1,
    )
    surfaces = {request.surface for request in requests}
    assert Surface.SERVICE_PORTAL not in surfaces


def test_service_portal_adapter_gates_the_surface():
    adapters = default_adapter_registry()
    adapter = adapters.resolve(
        platform_id="municipium",
        surface=Surface.SERVICE_PORTAL.value,
        capability="authenticated_service",
    )
    assert adapter is not None
    assert adapter.name == "service_portal"


# ── Hit: an official, credential-free pointer at INDIRECT ────────────────────

def test_discovered_service_yields_indirect_pointer():
    batch = _runtime(_inventory()).execute(
        _request(), platform_id="municipium", mappa=_mappa(), esito=None
    )
    assert batch is not None
    assert batch.status is DataStatus.FULFILLED
    assert batch.access_mode is AccessMode.INDIRECT
    assert batch.surface is Surface.SERVICE_PORTAL
    assert len(batch.records) == 1
    record = batch.records[0]
    assert record["url"] == PORTAL_URL
    assert record["requires_authentication"] is True
    assert record["authentication"] == ["spid", "cie"]
    assert record["role"] == "telematics_desk"


def test_pointer_never_carries_credentials():
    batch = _runtime(_inventory()).execute(
        _request(), platform_id="municipium", mappa=_mappa(), esito=None
    )
    forbidden = {"password", "token", "credentials", "session", "cookie"}
    assert forbidden.isdisjoint(batch.records[0].keys())


# ── Miss: unknown service or missing inventory → NOT_FOUND, no guess ─────────

def test_unknown_service_id_is_not_found():
    batch = _runtime(_inventory()).execute(
        _request(service_id="https://sportello.comune.prova.it/altro"),
        platform_id="municipium",
        mappa=_mappa(),
        esito=None,
    )
    assert batch is not None
    assert batch.status is DataStatus.NOT_FOUND
    assert batch.records == ()


def test_missing_inventory_is_not_found():
    batch = _runtime(None).execute(
        _request(), platform_id="municipium", mappa=_mappa(), esito=None
    )
    assert batch is not None
    assert batch.status is DataStatus.NOT_FOUND
    assert batch.records == ()


def test_source_id_mismatch_is_rejected():
    connector = ServicePortalConnettore(inventory_loader=lambda source_id: _inventory())
    request = _request().model_copy(update={"source_id": "999999"})
    with pytest.raises(ValueError):
        connector.retrieve(request, mappa=_mappa(), esito=None)
