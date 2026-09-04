"""Golden tests for the PeopleWeb–OpenWeb service connector (Base candidate).

Net-free: the network is behind the injected ``ServiceFetcher``.  OpenWeb reuses
the WP/AgID resolution whole, so these tests pin only what OpenWeb re-pins:

- the platform gate admits ``peopleweb`` and nothing else (not ``wordpress_agid``);
- the OpenWeb ``service_id`` prefix (``:openweb:``) and provider are distinct;
- Siscom (same ``peopleweb`` id, ``servizi.esposto=False``) is excluded
  structurally — ``_discovery_target`` returns ``None`` → ``NOT_SUPPORTED`` and
  the fetcher is never touched;
- exactly-one on an exposed OpenWeb comune resolves to one ``ServiceReference``.
"""

from __future__ import annotations

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import (
    DataRequest,
    DataStatus,
    FreshnessPolicy,
)
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.openweb_service import (
    OpenWebServiceConnector,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

# OpenWeb comune (Cuneo, from recon): exposed WordPress ``servizi`` CPT.
_ISTAT = "004078"
_BASE = "www.comune.cuneo.it"


# ── doubles ─────────────────────────────────────────────────────────────────


class StubFetcher:
    """A ``ServiceFetcher`` returning canned candidates and page HTML.

    Records whether ``scopri_servizi`` was called so a Siscom test can assert
    the connector self-excluded before touching the network."""

    def __init__(
        self,
        *,
        candidati: tuple[ServiceCandidate, ...] = (),
        pagine: dict[str, str] | None = None,
    ) -> None:
        self._candidati = candidati
        self._pagine = pagine or {}
        self.chiamato = False
        self.pagine_lette: list[str] = []

    def scopri_servizi(self, *, base_url, term, limit):
        self.chiamato = True
        return self._candidati

    def leggi_pagina(self, *, url, official_host):
        self.pagine_lette.append(url)
        return self._pagine.get(url)


def _mappa(
    *,
    istat: str = _ISTAT,
    sito: str | None = _BASE,
    esposto: bool = True,
) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=istat,
        nome="Cuneo",
        sito=sito,
        sondato_il="2026-09-04T00:00:00+00:00",
        # Both OpenWeb and Siscom carry this one platform_id at runtime.
        piattaforma_id="peopleweb",
        servizi=AssetServizi(esposto=esposto, rest_base="servizi", totale=64),
    )


def _request(
    *,
    source_id: str = _ISTAT,
    service_key: ServiceKey | str | None = ServiceKey.TRIBUTI_IMU,
    surface: Surface = Surface.ORDINARY_DATA,
    capability: str = CAPABILITY_SERVICES,
) -> DataRequest:
    selection: dict[str, object] = {}
    if service_key is not None:
        selection["service_key"] = (
            service_key.value if isinstance(service_key, ServiceKey) else service_key
        )
    return DataRequest(
        request_id=f"t:{source_id}:{surface.value}:{capability}",
        source_id=source_id,
        surface=surface,
        capability=capability,
        selection=selection,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def _candidato(
    wid: int,
    title: str = "IMU - Imposta municipale propria",
    url: str = f"https://{_BASE}/servizi/imu/",
) -> ServiceCandidate:
    return ServiceCandidate(native_id=str(wid), title=title, url=url)


# ── supports() — the platform gate OpenWeb re-pins ──────────────────────────


def test_supports_true_for_peopleweb_ordinary_services():
    c = OpenWebServiceConnector(StubFetcher())
    assert c.supports(_request(), platform_id="peopleweb") is True


def test_supports_false_for_wordpress_agid():
    # OpenWeb must NOT grab WP/AgID comuni — that stays the pilot's job.
    c = OpenWebServiceConnector(StubFetcher())
    assert c.supports(_request(), platform_id="wordpress_agid") is False


def test_supports_false_for_foreign_platform_and_empty():
    c = OpenWebServiceConnector(StubFetcher())
    assert c.supports(_request(), platform_id="municipium") is False
    assert c.supports(_request(), platform_id="") is False


def test_supports_false_for_service_portal_surface():
    c = OpenWebServiceConnector(StubFetcher())
    req = _request(surface=Surface.SERVICE_PORTAL)
    assert c.supports(req, platform_id="peopleweb") is False


def test_supports_false_for_other_capability():
    c = OpenWebServiceConnector(StubFetcher())
    req = _request(capability="offices")
    assert c.supports(req, platform_id="peopleweb") is False


# ── Siscom exclusion — structural, via servizi.esposto=False ────────────────


def test_siscom_esposto_false_is_not_supported_without_fetch():
    """Same ``peopleweb`` id, but Siscom carries ``esposto=False``: the inherited
    discovery target self-excludes → NOT_SUPPORTED, and the network is never hit."""
    fetcher = StubFetcher(candidati=(_candidato(1),))
    c = OpenWebServiceConnector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(esposto=False), esito=None)
    assert result.status is DataStatus.NOT_SUPPORTED
    assert fetcher.chiamato is False


# ── exactly-one resolution + OpenWeb identity ───────────────────────────────


def test_exactly_one_resolves_with_openweb_prefix():
    fetcher = StubFetcher(candidati=(_candidato(1234),))
    c = OpenWebServiceConnector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.FULFILLED
    assert len(result.service_references) == 1
    # Identity is the OpenWeb-tagged WP id, never conflated with the pilot's :wp:.
    assert result.service_references[0].service_id == f"{_ISTAT}:openweb:1234"


def test_zero_confirmed_is_not_found():
    # A candidate whose title does not match the key → 0 confirmed → honest miss.
    fetcher = StubFetcher(candidati=(_candidato(9, title="Prenotazione appuntamenti"),))
    c = OpenWebServiceConnector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND


def test_two_confirmed_collapses_to_not_found():
    # ≥2 confirmed and OpenWeb does not opt into disambiguation → NOT_FOUND (I-1).
    fetcher = StubFetcher(
        candidati=(
            _candidato(1, url=f"https://{_BASE}/servizi/imu-a/"),
            _candidato(2, url=f"https://{_BASE}/servizi/imu-b/"),
        )
    )
    c = OpenWebServiceConnector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND
