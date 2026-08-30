"""Golden tests per ``MagnoliaServiceConnector`` (aggancio del rail al runtime).

Net-free: il connettore riceve un ``lettore`` iniettato che ritorna un
``EsitoMagnoliaServizi`` costruito a mano (nessun ``storico.db``, nessuna rete).
Pinnano il contratto del wrapper — supports gating, gate esattamente-1,
``service_id`` dall'URL (mai dal titolo), MEDIATED, variant B/irraggiungibile →
miss onesto — e la precedenza del resolver (cache → catalogo → live) col
connettore Magnolia registrato.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from treasureiq.catalog import service_cache, service_catalog, service_resolver
from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.contracts import AccessMode, Surface
from treasureiq.catalog.data_contracts import DataStatus
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_connectors.magnolia_service import (
    MagnoliaServiceConnector,
)
from treasureiq.catalog.service_contracts import ServiceAccessMode, ServiceKey
from treasureiq.magnolia import EsitoMagnoliaServizi, ServizioMagnolia
from treasureiq.mappa_connettore import MappaConnettore

_ISTAT = "008017"  # Cervo
_HOME = "https://www.comune.cervo.im.it/"


def _servizio(titolo: str, url: str, sk: str | None, categoria: str = "106") -> ServizioMagnolia:
    from treasureiq.magnolia import _host_di

    return ServizioMagnolia(
        titolo=titolo, url=url, host=_host_di(url), categoria=categoria, service_key=sk
    )


def _esito_ok(servizi: list[ServizioMagnolia]) -> EsitoMagnoliaServizi:
    return EsitoMagnoliaServizi(
        esito="ok" if servizi else "vuoto",
        codice_istat=_ISTAT,
        comune="Cervo",
        home=_HOME,
        variante="strutturata",
        servizi=servizi,
        per_categoria={"106": len(servizi), "109": 0, "113": 0},
        service_keys=sorted({s.service_key for s in servizi if s.service_key}),
    )


def _lettore(esito: EsitoMagnoliaServizi):
    def leggi(codice_istat: str, **_):
        assert codice_istat == _ISTAT
        return esito

    return leggi


def _mappa() -> MappaConnettore:
    return MappaConnettore(
        codice_istat=_ISTAT, nome="Cervo", sito=None, sondato_il="2026-01-01T00:00:00+00:00"
    )


@pytest.fixture(autouse=True)
def _live_dir(monkeypatch, tmp_path):
    # Isola la cache servizi su tmp: nessuna scrittura sul path reale.
    monkeypatch.setattr(service_cache, "LIVE_DIR", tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- #
# supports                                                                     #
# --------------------------------------------------------------------------- #
def test_supports_solo_magnolia_ordinary_services():
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([])))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    assert c.supports(req, platform_id="magnolia") is True
    assert c.supports(req, platform_id="wordpress") is False


def test_supports_falso_su_surface_sbagliata():
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([])))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    finto = req.model_copy(update={"surface": Surface.TRANSPARENCY})
    assert c.supports(finto, platform_id="magnolia") is False


# --------------------------------------------------------------------------- #
# retrieve — gate esattamente-1 e forma del ConnectorResult                    #
# --------------------------------------------------------------------------- #
def test_retrieve_fulfilled_un_solo_match():
    cie = _servizio(
        "Carta d'identità elettronica (CIE)",
        "https://servizi.comune.cervo.im.it/istanze/carta-identita",
        "CARTA_IDENTITA",
    )
    altro = _servizio(
        "Cambio di residenza",
        "https://servizi.comune.cervo.im.it/istanze/residenza",
        "CAMBIO_RESIDENZA",
    )
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([cie, altro])))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    res = c.retrieve(req, mappa=_mappa())

    assert res.status is DataStatus.FULFILLED
    assert res.access_mode is AccessMode.MEDIATED  # HTML-scrape, mai DIRECT
    assert len(res.service_references) == 1
    ref = res.service_references[0]
    assert str(ref.source_url) == "https://servizi.comune.cervo.im.it/istanze/carta-identita"
    assert ref.provider_platform == "magnolia"
    assert len(ref.options) == 1
    assert ref.options[0].mode is ServiceAccessMode.INFORMATION
    assert res.connector.name == "magnolia_service"
    assert res.evidence and res.evidence[0].field == "url"


def test_service_id_dallurl_mai_dal_titolo():
    cie = _servizio(
        "Carta d'identità elettronica",
        "https://servizi.comune.cervo.im.it/istanze/carta-identita",
        "CARTA_IDENTITA",
    )
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([cie])))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    ref = c.retrieve(req, mappa=_mappa()).service_references[0]
    assert ref.service_id == f"{_ISTAT}:magnolia:carta-identita"
    assert "identità" not in ref.service_id.lower()
    assert "elettronica" not in ref.service_id.lower()


def test_retrieve_miss_zero_match():
    # Moricone/Ferriere thin: nessun servizio per la key richiesta.
    residenza = _servizio(
        "Cambio di residenza",
        "https://servizi.comune.example.it/istanze/residenza",
        "CAMBIO_RESIDENZA",
    )
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([residenza])))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    res = c.retrieve(req, mappa=_mappa())
    assert res.status is DataStatus.NOT_FOUND
    assert res.service_references == ()


def test_retrieve_ambiguo_due_match():
    a = _servizio("Carta d'identità", "https://x.comune.example.it/a", "CARTA_IDENTITA")
    b = _servizio("Carta identità elettronica", "https://x.comune.example.it/b", "CARTA_IDENTITA")
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([a, b])))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    res = c.retrieve(req, mappa=_mappa())
    assert res.status is DataStatus.NOT_FOUND  # ≥2 → mai scelta implicita


@pytest.mark.parametrize("esito_val,variante", [
    ("variante_non_strutturata", "non_strutturata"),
    ("irraggiungibile", "irraggiungibile"),
])
def test_retrieve_variant_b_e_irraggiungibile_miss_onesto(esito_val, variante):
    esito = EsitoMagnoliaServizi(
        esito=esito_val, codice_istat=_ISTAT, comune="Cervo", home=_HOME, variante=variante
    )
    c = MagnoliaServiceConnector(lettore=_lettore(esito))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    res = c.retrieve(req, mappa=_mappa())
    assert res.status is DataStatus.NOT_SUPPORTED
    assert res.access_mode is AccessMode.UNAVAILABLE


def test_retrieve_source_id_mismatch_solleva():
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([])))
    req = service_request(source_id="099999", service_key=ServiceKey.CARTA_IDENTITA)
    with pytest.raises(ValueError):
        c.retrieve(req, mappa=_mappa())  # mappa.codice_istat == _ISTAT ≠ source_id


# --------------------------------------------------------------------------- #
# precedenza resolver: cache → catalogo → live                                #
# --------------------------------------------------------------------------- #
def _registry_con(connettore) -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(connettore)
    return reg


def test_resolver_live_poi_scrive_cache():
    cie = _servizio(
        "Carta d'identità elettronica",
        "https://servizi.comune.cervo.im.it/istanze/carta-identita",
        "CARTA_IDENTITA",
    )
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([cie])))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    resolved = service_resolver.resolve_service_with_meta(
        req, mappa=_mappa(), registry=_registry_con(c), platform_id="magnolia"
    )
    assert resolved is not None
    assert resolved.from_cache is False
    assert resolved.connector.name == "magnolia_service"
    # scritto in cache: una seconda risoluzione col lettore che esplode resta hit
    def esplode(*_a, **_k):
        raise AssertionError("live non deve essere chiamato: cache hit atteso")

    c2 = MagnoliaServiceConnector(lettore=esplode)
    hit = service_resolver.resolve_service_with_meta(
        req, mappa=_mappa(), registry=_registry_con(c2), platform_id="magnolia"
    )
    assert hit is not None and hit.from_cache is True


def test_resolver_cache_precede_live():
    # Nessuna cache pre-seed qui: la precedenza cache è già provata sopra col
    # secondo giro; questa prova che un lettore che esplode NON è chiamato quando
    # la cache è calda (delegato al test sopra). Qui provo il miss onesto → None.
    residenza = _servizio(
        "Cambio di residenza", "https://x.comune.example.it/r", "CAMBIO_RESIDENZA"
    )
    c = MagnoliaServiceConnector(lettore=_lettore(_esito_ok([residenza])))
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    resolved = service_resolver.resolve_service_with_meta(
        req, mappa=_mappa(), registry=_registry_con(c), platform_id="magnolia"
    )
    assert resolved is None  # NOT_FOUND → nessun dato coniato


def test_resolver_catalogo_precede_live(monkeypatch):
    # Catalogo flat ON + hit → risolve senza toccare il connettore live.
    from treasureiq.catalog.service_contracts import ServiceAccessOption, ServiceReference

    ref = ServiceReference(
        service_id=f"{_ISTAT}:magnolia:carta-identita",
        title="Carta d'identità elettronica",
        source_url="https://servizi.comune.cervo.im.it/istanze/carta-identita",
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION,
                url="https://servizi.comune.cervo.im.it/istanze/carta-identita",
            ),
        ),
        discovered_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setenv("TREASUREIQ_SERVICE_CATALOG", "1")
    monkeypatch.setattr(service_catalog, "carica", lambda s, k: ref)

    def esplode(*_a, **_k):
        raise AssertionError("catalogo deve precedere il live")

    c = MagnoliaServiceConnector(lettore=esplode)
    req = service_request(source_id=_ISTAT, service_key=ServiceKey.CARTA_IDENTITA)
    resolved = service_resolver.resolve_service_with_meta(
        req, mappa=_mappa(), registry=_registry_con(c), platform_id="magnolia"
    )
    assert resolved is not None
    assert resolved.from_cache is True
    assert resolved.connector.name == "catalog"
