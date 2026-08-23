"""Golden tests for the service resolver (Ramo 3, Slice 3 + Slice 5 envelope).

Pure unit tests: ``LIVE_DIR``→``tmp_path``, a stub connector (records its calls),
no network. They pin the resolver contract — cache-first, write-through only on
a coherent single-reference success, the review guards, the barrier that keeps it
from crossing the ``ServicePortalConnettore`` — and the Slice 5 **envelope**
(``resolve_service_with_meta``): cache-hit vs live provenance, ``retrieved_at``
and ``connector`` preserved, ``discovered_at`` never used for freshness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from treasureiq.catalog import service_cache, service_resolver
from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import CAPABILITY_SERVICES, AccessMode, FreshnessStatus, Surface
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataRequest,
    DataStatus,
    Freshness,
    FreshnessPolicy,
)
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_contracts import (
    CachedService,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceCacheFile,
    ServiceKey,
    ServiceReference,
)
from treasureiq.mappa_connettore import MappaConnettore

_SOURCE = "058003"
_CONN = ConnectorRef(name="stub_service", version="1")


@pytest.fixture(autouse=True)
def _live_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(service_cache, "LIVE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def mappa():
    return MappaConnettore(
        codice_istat=_SOURCE, nome="Albano", sito=None, sondato_il="2026-01-01T00:00:00+00:00"
    )


@pytest.fixture
def request_cie():
    return service_request(source_id=_SOURCE, service_key=ServiceKey.CARTA_IDENTITA)


def _reference(service_id: str = "svc-cie") -> ServiceReference:
    return ServiceReference(
        service_id=service_id,
        title="Carta d'identità elettronica",
        source_url="https://comune.example.it/servizi/cie",
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.DOWNLOAD,
                url="https://comune.example.it/servizi/cie/modulo.pdf",
            ),
        ),
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _result(
    request: DataRequest,
    references: tuple[ServiceReference, ...],
    *,
    status: DataStatus = DataStatus.FULFILLED,
    source_id: str | None = None,
    request_id: str | None = None,
    connector: ConnectorRef | None = None,
    retrieved_at: datetime | None = None,
) -> ConnectorResult:
    return ConnectorResult(
        request_id=request_id or request.request_id,
        source_id=source_id or request.source_id,
        status=status,
        access_mode=AccessMode.DIRECT,
        service_references=references,
        freshness=Freshness(status=FreshnessStatus.FRESH),
        connector=connector or _CONN,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
    )


class _StubConnettore:
    """A SourceConnector that returns a canned result and counts retrieve()."""

    name = "stub_service"
    version = "1"

    def __init__(self, result: ConnectorResult | None, *, supports: bool = True):
        self._result = result
        self._supports = supports
        self.chiamate = 0

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        return self._supports

    def retrieve(self, request, *, mappa, esito) -> ConnectorResult:
        self.chiamate += 1
        return self._result


def _registry(connector: _StubConnettore) -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(connector)
    return reg


def _cached(source_id: str, ref: ServiceReference, *, quando: datetime, connector: ConnectorRef):
    """Write a v2 CachedService directly to disk for a controlled cache-hit."""
    voce = CachedService(
        service_key=ServiceKey.CARTA_IDENTITA,
        reference=ref,
        retrieved_at=quando,
        connector=connector,
    )
    percorso = service_cache.LIVE_DIR / "servizi-risolti" / f"{source_id}.json"
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(
        ServiceCacheFile(
            source_id=source_id, entries=(voce,), updated_at=datetime.now(timezone.utc)
        ).model_dump_json(),
        "utf-8",
    )


# 1 — fresh cache-hit → cached ref, connector never called
def test_cache_hit_non_chiama_connettore(mappa, request_cie):
    cached = _reference("cached")
    service_cache.salva(_SOURCE, ServiceKey.CARTA_IDENTITA, cached, _CONN)
    stub = _StubConnettore(_result(request_cie, (_reference("live"),)))
    got = service_resolver.resolve_service(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    assert got == cached
    assert stub.chiamate == 0


# 2 — cache-miss → connector FULFILLED with one ref → returns it AND populates cache
def test_miss_chiama_connettore_e_popola(mappa, request_cie):
    ref = _reference("live")
    stub = _StubConnettore(_result(request_cie, (ref,)))
    got = service_resolver.resolve_service(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    assert got == ref
    assert stub.chiamate == 1
    # write-through: a subsequent load is a hit
    letto = service_cache.carica(_SOURCE, ServiceKey.CARTA_IDENTITA, policy=request_cie.freshness)
    assert letto is not None and letto.reference == ref


# 3 — stale cache → connector re-resolves, cache rewritten
def test_stale_re_risolve(mappa, request_cie):
    _cached(
        _SOURCE,
        _reference("old"),
        quando=datetime.now(timezone.utc) - timedelta(days=2),
        connector=_CONN,
    )
    fresco = _reference("fresh")
    stub = _StubConnettore(_result(request_cie, (fresco,)))
    got = service_resolver.resolve_service(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    assert got == fresco
    assert stub.chiamate == 1


# 4 — connector NOT_FOUND → None, nothing written
def test_connettore_not_found_non_scrive(mappa, request_cie):
    stub = _StubConnettore(_result(request_cie, (), status=DataStatus.NOT_FOUND))
    got = service_resolver.resolve_service(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    assert got is None
    assert service_cache.carica(_SOURCE, ServiceKey.CARTA_IDENTITA, policy=request_cie.freshness) is None


# 5 — FULFILLED but empty references → None, nothing written (defensive)
def test_fulfilled_vuoto_non_scrive(mappa, request_cie):
    stub = _StubConnettore(_result(request_cie, ()))
    got = service_resolver.resolve_service(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    assert got is None
    assert service_cache.carica(_SOURCE, ServiceKey.CARTA_IDENTITA, policy=request_cie.freshness) is None


# 5b — FULFILLED with >1 references → None, nothing written
def test_fulfilled_multiplo_non_sceglie(mappa, request_cie):
    stub = _StubConnettore(_result(request_cie, (_reference("a"), _reference("b"))))
    got = service_resolver.resolve_service(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    assert got is None
    assert service_cache.carica(_SOURCE, ServiceKey.CARTA_IDENTITA, policy=request_cie.freshness) is None


# 6 — empty registry (no connector) → None, nothing written
def test_registry_vuoto(mappa, request_cie):
    got = service_resolver.resolve_service(
        request_cie, mappa=mappa, esito=None, registry=ConnectorRegistry()
    )
    assert got is None
    assert service_cache.carica(_SOURCE, ServiceKey.CARTA_IDENTITA, policy=request_cie.freshness) is None


# 6b — registry defaults to an empty instance when omitted
def test_registry_default_vuoto(mappa, request_cie):
    assert service_resolver.resolve_service(request_cie, mappa=mappa, esito=None) is None


# 7 — selection without service_key / outside vocabulary → None
def test_service_key_assente_o_fuori_vocabolario(mappa):
    senza = DataRequest(
        request_id=f"chat:{_SOURCE}:ordinary_data:services",
        source_id=_SOURCE,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection={},
        freshness=FreshnessPolicy(max_age_seconds=86400),
        manifest_revision=1,
    )
    fuori = senza.model_copy(update={"selection": {"service_key": "passaporto"}})
    assert service_resolver.resolve_service(senza, mappa=mappa, esito=None) is None
    assert service_resolver.resolve_service(fuori, mappa=mappa, esito=None) is None


# 8 — barrier: a SERVICE_PORTAL request is rejected before the cache
def test_guardia_surface_service_portal(mappa):
    sp = DataRequest(
        request_id=f"chat:{_SOURCE}:service_portal:x",
        source_id=_SOURCE,
        surface=Surface.SERVICE_PORTAL,
        capability=CAPABILITY_SERVICES,
        selection={"service_key": "carta_identita"},
        freshness=FreshnessPolicy(max_age_seconds=86400),
        manifest_revision=1,
    )
    with pytest.raises(ValueError):
        service_resolver.resolve_service(sp, mappa=mappa, esito=None)


# 8b — wrong capability rejected before the cache
def test_guardia_capability(mappa):
    req = DataRequest(
        request_id=f"chat:{_SOURCE}:ordinary_data:offices",
        source_id=_SOURCE,
        surface=Surface.ORDINARY_DATA,
        capability="offices",
        selection={"service_key": "carta_identita"},
        freshness=FreshnessPolicy(max_age_seconds=86400),
        manifest_revision=1,
    )
    with pytest.raises(ValueError):
        service_resolver.resolve_service(req, mappa=mappa, esito=None)


# 12 — result whose source_id/request_id disagree with the request → None, no write
def test_identita_risultato_incoerente(mappa, request_cie):
    for kwargs in ({"source_id": "058091"}, {"request_id": "chat:altro"}):
        stub = _StubConnettore(_result(request_cie, (_reference(),), **kwargs))
        got = service_resolver.resolve_service(
            request_cie, mappa=mappa, esito=None, registry=_registry(stub)
        )
        assert got is None
        assert service_cache.carica(
            _SOURCE, ServiceKey.CARTA_IDENTITA, policy=request_cie.freshness
        ) is None


# 9 — write-through preserves other service_keys already cached (no-clobber)
def test_write_through_preserva_altre_chiavi(mappa, request_cie):
    altro = _reference("tributi")
    service_cache.salva(_SOURCE, ServiceKey.TRIBUTI, altro, _CONN)
    ref = _reference("cie")
    stub = _StubConnettore(_result(request_cie, (ref,)))
    service_resolver.resolve_service(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    tributi = service_cache.carica(_SOURCE, ServiceKey.TRIBUTI, policy=request_cie.freshness)
    cie = service_cache.carica(_SOURCE, ServiceKey.CARTA_IDENTITA, policy=request_cie.freshness)
    assert tributi is not None and tributi.reference == altro
    assert cie is not None and cie.reference == ref


# --- Slice 5 envelope (D-S5-5) ---------------------------------------------


# E1 — cache-hit envelope: from_cache=True, retrieved_at + connector from cache,
#      connector never called; discovered_at is NOT the retrieved_at.
def test_envelope_cache_hit(mappa, request_cie):
    # recent enough for the FRESH window (request_cie policy), yet distinct from
    # the fixed discovered_at — so the envelope must NOT borrow discovered_at.
    quando = datetime.now(timezone.utc)
    conn = ConnectorRef(name="wordpress_agid_service", version="1")
    _cached(_SOURCE, _reference("cached"), quando=quando, connector=conn)
    stub = _StubConnettore(_result(request_cie, (_reference("live"),)))
    env = service_resolver.resolve_service_with_meta(
        request_cie, mappa=mappa, registry=_registry(stub)
    )
    assert env is not None
    assert env.from_cache is True
    assert env.retrieved_at == quando
    assert env.connector == conn
    assert env.reference.service_id == "cached"
    # freshness must never borrow discovered_at
    assert env.retrieved_at != env.reference.discovered_at
    assert stub.chiamate == 0


# E2 — live envelope: from_cache=False, retrieved_at + connector from ConnectorResult.
def test_envelope_live(mappa, request_cie):
    quando = datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc)
    conn = ConnectorRef(name="wordpress_agid_service", version="1")
    stub = _StubConnettore(
        _result(request_cie, (_reference("live"),), connector=conn, retrieved_at=quando)
    )
    env = service_resolver.resolve_service_with_meta(
        request_cie, mappa=mappa, registry=_registry(stub)
    )
    assert env is not None
    assert env.from_cache is False
    assert env.retrieved_at == quando
    assert env.connector == conn
    assert stub.chiamate == 1


# E3 — cache-hit = zero network + provenance preserved: a second identical request
#      after a live resolve does not call the connector again and keeps the connector.
def test_cache_hit_zero_rete_provenienza(mappa, request_cie):
    conn = ConnectorRef(name="wordpress_agid_service", version="1")
    stub = _StubConnettore(_result(request_cie, (_reference("live"),), connector=conn))
    first = service_resolver.resolve_service_with_meta(
        request_cie, mappa=mappa, registry=_registry(stub)
    )
    assert first is not None and first.from_cache is False
    # second pass: fresh cache-hit, connector NOT called again, provenance intact
    stub2 = _StubConnettore(_result(request_cie, (_reference("other"),), connector=conn))
    second = service_resolver.resolve_service_with_meta(
        request_cie, mappa=mappa, registry=_registry(stub2)
    )
    assert second is not None
    assert second.from_cache is True
    assert second.connector == conn
    assert second.reference.service_id == "live"
    assert stub2.chiamate == 0


# E4 (Fix D, Slice 5.2) — single retrieved_at: the value in the live envelope is
# the value persisted, and the cache hit replays exactly that instant (no drift
# between the connector fetch time and the cache write time).
def test_envelope_e_persistito_stesso_retrieved_at(mappa, request_cie):
    quando = datetime(2026, 8, 23, 14, 44, 34, tzinfo=timezone.utc)
    conn = ConnectorRef(name="wordpress_agid_service", version="1")
    stub = _StubConnettore(
        _result(request_cie, (_reference("live"),), connector=conn, retrieved_at=quando)
    )
    env = service_resolver.resolve_service_with_meta(
        request_cie, mappa=mappa, registry=_registry(stub)
    )
    assert env is not None and env.retrieved_at == quando
    persistito = service_cache.carica(
        _SOURCE, ServiceKey.CARTA_IDENTITA, policy=request_cie.freshness
    )
    assert persistito is not None
    assert persistito.retrieved_at == quando  # non l'ora di scrittura
    stub2 = _StubConnettore(_result(request_cie, (_reference("other"),), connector=conn))
    second = service_resolver.resolve_service_with_meta(
        request_cie, mappa=mappa, registry=_registry(stub2)
    )
    assert second is not None and second.from_cache is True
    assert second.retrieved_at == quando  # cache hit replays exactly that instant
