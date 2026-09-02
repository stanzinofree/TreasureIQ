"""Resolver: ramo DISAMBIGUATION e selezione (risolvi_o_disambigua / seleziona_servizio).

Estende i golden del resolver al caso ≥2: la risoluzione ritorna un
``DisambiguazioneServizi`` (mai cacheato), la façade ``resolve_service_with_meta``
lo collassa a ``None`` (comportamento storico invariato), e la selezione di un
``service_id`` risolve una singola reference senza scrivere cache. Net-free.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from treasureiq.catalog import service_cache, service_resolver
from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import AccessMode, FreshnessStatus
from treasureiq.catalog.data_contracts import ConnectorRef, DataStatus, Freshness
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_contracts import (
    DisambiguazioneServizi,
    ResolvedService,
    ServiceAccessMode,
    ServiceAccessOption,
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
        codice_istat=_SOURCE, nome="Albano", sito=None,
        sondato_il="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def request_cie():
    return service_request(source_id=_SOURCE, service_key=ServiceKey.CARTA_IDENTITA)


def _reference(service_id: str) -> ServiceReference:
    url = f"https://comune.example.it/servizi/{service_id}"
    return ServiceReference(
        service_id=service_id,
        title=f"Carta {service_id}",
        source_url=url,
        options=(
            ServiceAccessOption(mode=ServiceAccessMode.INFORMATION, url=url, source_url=url),
        ),
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _result(request, references, *, status, connector=None) -> ConnectorResult:
    return ConnectorResult(
        request_id=request.request_id,
        source_id=request.source_id,
        status=status,
        access_mode=AccessMode.MEDIATED,
        service_references=references,
        freshness=Freshness(status=FreshnessStatus.LIVE),
        connector=connector or _CONN,
        retrieved_at=datetime.now(timezone.utc),
    )


class _StubConnettore:
    """SourceConnector di test: canned retrieve + canned seleziona per service_id."""

    name = "stub_service"
    version = "1"

    def __init__(self, retrieve_result=None, seleziona_map=None):
        self._retrieve_result = retrieve_result
        self._seleziona_map = seleziona_map or {}
        self.retrieve_chiamate = 0
        self.seleziona_chiamate = 0

    def supports(self, request, *, platform_id: str) -> bool:
        return True

    def retrieve(self, request, *, mappa, esito) -> ConnectorResult:
        self.retrieve_chiamate += 1
        return self._retrieve_result

    def seleziona(self, request, *, mappa, service_id) -> ConnectorResult:
        self.seleziona_chiamate += 1
        refs = self._seleziona_map.get(service_id, ())
        status = DataStatus.FULFILLED if refs else DataStatus.NOT_FOUND
        return _result(request, refs, status=status)


def _registry(connector) -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(connector)
    return reg


def _cache_vuota(request) -> bool:
    return service_cache.carica(
        _SOURCE, ServiceKey.CARTA_IDENTITA, policy=request.freshness
    ) is None


# -- ≥2 → DisambiguazioneServizi, mai cacheato ------------------------------


def test_ge2_ritorna_disambiguazione_no_cache(mappa, request_cie):
    refs = (_reference("cie"), _reference("carta"))
    stub = _StubConnettore(_result(request_cie, refs, status=DataStatus.DISAMBIGUATION))
    esito = service_resolver.risolvi_o_disambigua(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    assert isinstance(esito, DisambiguazioneServizi)
    assert {r.service_id for r in esito.references} == {"cie", "carta"}
    assert esito.connector == _CONN
    # Non cacheato: la lista è del turno, non un dato promosso per la key.
    assert _cache_vuota(request_cie)


def test_facade_meta_collassa_disambiguazione_a_none(mappa, request_cie):
    # resolve_service_with_meta è la façade single-only: DISAMBIGUATION → None,
    # esattamente il miss che i chiamanti storici già gestiscono (nessuna regressione).
    refs = (_reference("cie"), _reference("carta"))
    stub = _StubConnettore(_result(request_cie, refs, status=DataStatus.DISAMBIGUATION))
    got = service_resolver.resolve_service_with_meta(
        request_cie, mappa=mappa, esito=None, registry=_registry(stub)
    )
    assert got is None


# -- selezione: lookup di un service_id, nessuna scrittura cache ------------


def test_seleziona_id_noto_fulfilled_no_cache(mappa, request_cie):
    scelta = _reference("carta")
    stub = _StubConnettore(seleziona_map={"carta": (scelta,)})
    got = service_resolver.seleziona_servizio(
        request_cie, mappa=mappa, service_id="carta", registry=_registry(stub)
    )
    assert isinstance(got, ResolvedService)
    assert got.reference.service_id == "carta"
    assert got.from_cache is False
    assert stub.seleziona_chiamate == 1
    # La scelta NON entra in cache: scavalcherebbe la disambiguazione per tutti.
    assert _cache_vuota(request_cie)


def test_seleziona_id_ignoto_none(mappa, request_cie):
    stub = _StubConnettore(seleziona_map={"carta": (_reference("carta"),)})
    got = service_resolver.seleziona_servizio(
        request_cie, mappa=mappa, service_id="ignoto-999", registry=_registry(stub)
    )
    assert got is None
    assert _cache_vuota(request_cie)
