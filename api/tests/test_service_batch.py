"""Golden tests for the service DataBatch builder (Ramo 3, Slice 5, §1.4).

Pure, no network. Pin the builder contract: MEDIATED/FULFILLED DataBatch,
``Freshness`` taken from the **envelope** (FRESH for a cache-hit, LIVE for a live
call, ``retrieved_at`` of the resolution, never ``discovered_at``), one typed
record per access option (D-S5-3), and — the key invariant — cache-hit and live
produce the **same** batch apart from the freshness block.
"""

from __future__ import annotations

from datetime import datetime, timezone

from treasureiq.catalog.contracts import ConnectorRef
from treasureiq.catalog.data_contracts import AccessMode, DataStatus, FreshnessStatus
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_batch import service_reference_batch
from treasureiq.catalog.service_contracts import (
    AuthenticationMethod,
    ResolvedService,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
    ServiceReference,
)

_SOURCE = "058003"
_CONN = ConnectorRef(name="wordpress_agid_service", version="1")
_QUANDO = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _reference() -> ServiceReference:
    return ServiceReference(
        service_id=f"{_SOURCE}:wp:42",
        title="Carta d'identità elettronica",
        source_url="https://comune.example.it/servizi/cie",
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION,
                url="https://comune.example.it/servizi/cie",
            ),
            ServiceAccessOption(
                mode=ServiceAccessMode.DOWNLOAD,
                url="https://comune.example.it/servizi/cie/modulo.pdf",
                source_url="https://comune.example.it/servizi/cie",
            ),
            ServiceAccessOption(
                mode=ServiceAccessMode.AUTHENTICATED_ONLINE,
                url="https://portale.example.it/cie",
                authentication=(AuthenticationMethod.SPID, AuthenticationMethod.CIE),
                requires_authentication=True,
            ),
        ),
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _resolved(*, from_cache: bool) -> ResolvedService:
    return ResolvedService(
        reference=_reference(),
        retrieved_at=_QUANDO,
        from_cache=from_cache,
        connector=_CONN,
    )


def _request():
    return service_request(source_id=_SOURCE, service_key=ServiceKey.CARTA_IDENTITA)


# 1 — live envelope → LIVE freshness, MEDIATED/FULFILLED, connector + transport
def test_batch_live():
    batch = service_reference_batch(_resolved(from_cache=False), _request())
    assert batch.status is DataStatus.FULFILLED
    assert batch.access_mode is AccessMode.MEDIATED
    assert batch.freshness.status is FreshnessStatus.LIVE
    assert batch.freshness.retrieved_at == _QUANDO
    assert batch.connector == _CONN
    assert batch.transport.from_cache is False
    assert batch.service_references == (_reference(),)


# 2 — cache envelope → FRESH freshness, from_cache transport
def test_batch_cache():
    batch = service_reference_batch(_resolved(from_cache=True), _request())
    assert batch.freshness.status is FreshnessStatus.FRESH
    assert batch.freshness.retrieved_at == _QUANDO
    assert batch.transport.from_cache is True


# 3 — freshness never borrows discovered_at
def test_freshness_non_usa_discovered_at():
    resolved = _resolved(from_cache=True)
    batch = service_reference_batch(resolved, _request())
    assert batch.freshness.retrieved_at != resolved.reference.discovered_at


# 4 — one typed record per option, service_id explicit (D-S5-3)
def test_records_tipizzati_per_opzione():
    batch = service_reference_batch(_resolved(from_cache=False), _request())
    assert len(batch.records) == 3
    modi = [r["mode"] for r in batch.records]
    assert modi == [
        ServiceAccessMode.INFORMATION.value,
        ServiceAccessMode.DOWNLOAD.value,
        ServiceAccessMode.AUTHENTICATED_ONLINE.value,
    ]
    for r in batch.records:
        assert r["service_id"] == f"{_SOURCE}:wp:42"
        assert set(r) == {
            "service_id",
            "mode",
            "url",
            "source_url",
            "requires_authentication",
            "authentication",
        }
    auth = next(r for r in batch.records if r["mode"] == ServiceAccessMode.AUTHENTICATED_ONLINE.value)
    assert auth["requires_authentication"] is True
    assert auth["authentication"] == ("spid", "cie")


# 5 — same form, different freshness: cache-hit and live differ ONLY in freshness
#     + transport (the review's explicit invariant, §5).
def test_stessa_forma_freshness_diversa():
    live = service_reference_batch(_resolved(from_cache=False), _request())
    cache = service_reference_batch(_resolved(from_cache=True), _request())
    campi = ("records", "service_references", "evidence", "connector", "access_mode", "status")
    for campo in campi:
        assert getattr(live, campo) == getattr(cache, campo), campo
    assert live.freshness.status is not cache.freshness.status
    assert live.transport.from_cache != cache.transport.from_cache


# 6 — evidence points at each option URL
def test_evidence_da_ogni_opzione():
    batch = service_reference_batch(_resolved(from_cache=False), _request())
    urls = {e.evidence_id for e in batch.evidence}
    assert urls == {
        "https://comune.example.it/servizi/cie",
        "https://comune.example.it/servizi/cie/modulo.pdf",
        "https://portale.example.it/cie",
    }
