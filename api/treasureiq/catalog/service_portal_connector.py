"""Deterministic SERVICE_PORTAL executor over the persisted inventory.

The institutional site discovers a service portal; the portal itself is
authenticated and citizen-operated.  This connector never logs in and never
retrieves data behind authentication: it turns a previously discovered
``ServicePortalCandidate`` into an honest *pointer* to the official portal
(URL, role, accepted authentication methods) so the chat rail can hand the
citizen off without pretending TIQ can act as them.

The access mode is therefore ``INDIRECT`` — TIQ mediates neither the login nor
the data, it only surfaces the official entrypoint already confirmed by
discovery.  There is no network call here: the entrypoints come from the
inventory persisted by ``discover_source_inventory``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import AccessMode, FreshnessStatus, Surface
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
    TransportMeta,
)
from treasureiq.catalog.service_contracts import ServicePortalCandidate, SourceInventory
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore

SERVICE_PORTAL_VERSION = "1"

#: Loader signature: given a source_id, return its persisted inventory or None.
InventoryLoader = Callable[[str], "SourceInventory | None"]


def _inventory_from_live(source_id: str) -> SourceInventory | None:
    """Read the inventory a sweep persisted for one municipality, if any."""
    from treasureiq.sonda_live import LIVE_DIR

    path = Path(LIVE_DIR) / "inventario" / f"{source_id}.json"
    if not path.exists():
        return None
    try:
        return SourceInventory.model_validate_json(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 — a corrupt inventory is a miss, not a crash
        return None


def _project_candidate(candidate: ServicePortalCandidate) -> dict[str, Any]:
    """Project one discovered SP entrypoint into an honest, credential-free pointer."""
    return {
        "url": str(candidate.url),
        "label": candidate.label,
        "role": candidate.role.value,
        "access_mode": candidate.access_mode.value,
        "requires_authentication": True,
        "authentication": [method.value for method in candidate.authentication],
        "capabilities": list(candidate.capabilities),
        "provider_hint": candidate.provider_hint,
        "platform_id": candidate.platform_id,
        "source_url": str(candidate.source_url),
    }


class ServicePortalConnettore:
    """Surface a previously discovered service portal as an official pointer.

    ``service_id`` is the entrypoint URL selected upstream from a
    ``ServiceReference``/``ServicePortalCandidate``; candidates carry no
    separate identifier, so the confirmed URL is the stable key.  This
    connector matches by that URL and never guesses one.
    """

    name = "service_portal"
    version = SERVICE_PORTAL_VERSION

    def __init__(self, inventory_loader: InventoryLoader | None = None) -> None:
        self._load_inventory = inventory_loader or _inventory_from_live

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        return request.surface is Surface.SERVICE_PORTAL

    def retrieve(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> ConnectorResult:
        if request.source_id != mappa.codice_istat:
            raise ValueError("request.source_id does not match the measured source")

        service_id = request.selection.get("service_id")
        inventory = self._load_inventory(request.source_id)
        candidate = self._match(inventory, service_id)
        if candidate is None:
            return self._miss(request, inventory)

        record = _project_candidate(candidate)
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=DataStatus.FULFILLED,
            access_mode=AccessMode.INDIRECT,
            records=(record,),
            evidence=(EvidenceRef(evidence_id=record["url"], field="url"),),
            freshness=Freshness(
                status=FreshnessStatus.FRESH,
                retrieved_at=inventory.updated_at if inventory else None,
            ),
            limitations=(
                "TIQ indica il portale ufficiale ma non effettua l'accesso: "
                "l'autenticazione resta al cittadino.",
            ),
            transport=TransportMeta(from_cache=True),
            connector=ConnectorRef(name=self.name, version=self.version),
            retrieved_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _match(
        inventory: SourceInventory | None, service_id: Any
    ) -> ServicePortalCandidate | None:
        if inventory is None or not service_id:
            return None
        for candidate in inventory.service_portals:
            if str(candidate.url) == str(service_id):
                return candidate
        return None

    def _miss(
        self, request: DataRequest, inventory: SourceInventory | None
    ) -> ConnectorResult:
        limitation = (
            "Nessun inventario servizi disponibile per questa fonte."
            if inventory is None
            else "Il servizio richiesto non è tra i portali confermati per questa fonte."
        )
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=DataStatus.NOT_FOUND,
            access_mode=AccessMode.INDIRECT,
            freshness=Freshness(status=FreshnessStatus.UNKNOWN),
            limitations=(limitation,),
            connector=ConnectorRef(name=self.name, version=self.version),
        )
