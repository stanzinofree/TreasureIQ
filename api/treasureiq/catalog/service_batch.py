"""``DataBatch`` da un ``ResolvedService`` risolto (Ramo 3, Slice 5).

Builder **puro** che confeziona l'envelope del resolver in un ``DataBatch``
``ORDINARY_DATA/CAPABILITY_SERVICES``, ``access_mode=MEDIATED``. Stessa forma per
cache-hit e per live: cambia **solo** il blocco ``Freshness``, preso
dall'envelope (mai da ``reference.discovered_at``, §1.0/§1.4).
"""

from __future__ import annotations

from treasureiq.catalog.contracts import FreshnessStatus
from treasureiq.catalog.data_contracts import (
    AccessMode,
    DataBatch,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
    TransportMeta,
)
from treasureiq.catalog.service_contracts import ResolvedService, ServiceAccessOption


def _record(service_id: str, opzione: ServiceAccessOption) -> dict:
    """Una riga tipizzata per opzione (D-S5-3), col ``service_id`` esplicito.

    Nessun campo dedotto dal titolo: il ``service_id`` è quello della reference
    (``{source_id}:wp:{wordpress_id}``), l'URL è già validato in Slice 4.
    """
    return {
        "service_id": service_id,
        "mode": opzione.mode.value,
        "url": str(opzione.url),
        "source_url": str(opzione.source_url) if opzione.source_url else None,
        "requires_authentication": opzione.requires_authentication,
        "authentication": tuple(metodo.value for metodo in opzione.authentication),
        # Provenienza SP arricchita read-time (Ramo 3, Slice 6): `None` su
        # un'opzione Base pura (nessun aggancio SP), valorizzata sull'opzione
        # AUTHENTICATED_ONLINE con evidenza per-link. Viaggia nel DataBatch.
        "sp_platform_id": opzione.sp_platform_id,
        "sp_role": opzione.sp_role.value if opzione.sp_role else None,
        "sp_fingerprint": opzione.sp_fingerprint,
    }


def service_reference_batch(resolved: ResolvedService, request: DataRequest) -> DataBatch:
    """Confeziona l'envelope risolto in un ``DataBatch`` MEDIATED FULFILLED.

    ``Freshness`` dall'envelope: ``FRESH`` per un cache-hit, ``LIVE`` per una
    chiamata dal vivo, con il ``retrieved_at`` della risoluzione (non della
    scoperta). ``connector`` = provenienza dell'envelope. Un record tipizzato
    per opzione di accesso.
    """
    reference = resolved.reference
    status = FreshnessStatus.FRESH if resolved.from_cache else FreshnessStatus.LIVE
    records = tuple(_record(reference.service_id, opzione) for opzione in reference.options)
    return DataBatch(
        request_id=request.request_id,
        status=DataStatus.FULFILLED,
        access_mode=AccessMode.MEDIATED,
        source_id=request.source_id,
        surface=request.surface,
        capability=request.capability,
        records=records,
        service_references=(reference,),
        evidence=tuple(
            EvidenceRef(evidence_id=str(opzione.url), field="url")
            for opzione in reference.options
        ),
        freshness=Freshness(status=status, retrieved_at=resolved.retrieved_at),
        transport=TransportMeta(from_cache=resolved.from_cache),
        connector=resolved.connector,
    )
