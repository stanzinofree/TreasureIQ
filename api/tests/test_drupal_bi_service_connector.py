"""Golden tests for the Drupal Bootstrap Italia service connector (Ramo 3, #4).

Net-free: the network is behind a stub transport serving captured fixtures of
real «Modello Comuni» portals.  The recon found the family exposes TWO index
layouts, both covered here against real markup:

- **showcase** (Torino, Dicomano, Almè): ``/servizi`` carries the BI *argomento*
  tiles; the full service list of a topic lives on the category page
  ``/servizi/<slug-argomento>``.  Services on the category page may be flat
  (``/servizi/<slug>``, Torino) or **nested** under the topic
  (``/servizi/<argomento>/<slug>``, small comuni) — the discriminator is the
  ``data-element="service-link"`` design token, never the path depth;
- **paginated index** (Monsummano, Padova): ``/servizi?page=N`` paginates all
  services and the tiles are absent from the static HTML (JS-rendered).  When no
  tile is found the connector falls back to paginating the index itself.

Both the bounded discovery and the shared ``retrieve`` contract are exercised
end-to-end: exactly-one → ServiceReference with the ``drupal`` id from the URL
path (never the title); 0 or ≥2 confirmed → NOT_FOUND (I-1, no implicit pick);
off-host anchors dropped (I-5); the argomento mapping total over ServiceKey.
"""

from __future__ import annotations

from pathlib import Path

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.service_connectors.drupal_bi_service import (
    DRUPAL_BI_ARGOMENTO,
    DrupalBiServiceConnector,
    _DrupalBiDiscovery,
)
from treasureiq.catalog.service_contracts import ServiceAccessMode, ServiceKey
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

_FIXTURES = Path(__file__).parent / "fixtures" / "drupal"


def _fix(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8", errors="ignore")


# ── doubles ─────────────────────────────────────────────────────────────────


class _StubTransport:
    """Serves canned HTML per-URL; records what was fetched.  Unknown URL → None
    (mirrors a muted/absent page, e.g. the ``?page=1`` probe past a 1-page
    category, or a service detail page we do not fixture)."""

    def __init__(self, pagine: dict[str, str]) -> None:
        self._pagine = pagine
        self.letti: list[str] = []

    def leggi_pagina(self, *, url, official_host):
        self.letti.append(url)
        return self._pagine.get(url)


class _FetcherDrupal:
    """Real ``_DrupalBiDiscovery`` over a stub transport → a ``ServiceFetcher``.

    Wiring the real discovery (not canned candidates) exercises the scrape +
    recogniser + exactly-one gate end-to-end, net-free."""

    def __init__(self, pagine: dict[str, str]) -> None:
        self.transport = _StubTransport(pagine)
        self._discovery = _DrupalBiDiscovery()

    def scopri_servizi(self, *, base_url, term, limit):
        return self._discovery.scopri_servizi(
            self.transport, base_url=base_url, term=term, limit=limit
        )

    def leggi_pagina(self, *, url, official_host):
        return self.transport.leggi_pagina(url=url, official_host=official_host)


_NON_PASSATO = object()  # sentinel: distinguishes "sito omesso" from "sito=None"


def _mappa(*, istat: str, host: str, sito=_NON_PASSATO) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=istat,
        nome=host,
        sito=host if sito is _NON_PASSATO else sito,
        sondato_il="2026-09-03T00:00:00+00:00",
        piattaforma_id="drupal",
        servizi=AssetServizi(esposto=False, rest_base=None, totale=0),
    )


def _request(
    *,
    source_id: str,
    service_key: ServiceKey | str | None,
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


def _connector(pagine: dict[str, str]) -> DrupalBiServiceConnector:
    return DrupalBiServiceConnector(_FetcherDrupal(pagine))


# ── real portals ────────────────────────────────────────────────────────────
# Dicomano (048013): small clean showcase; category pages nest services.
_DIC = "comune.dicomano.fi.it"
_DIC_INDEX = f"https://{_DIC}/servizi"
_DIC_ANAG = f"https://{_DIC}/servizi/anagrafe-e-stato-civile"
_DIC_TRIB = f"https://{_DIC}/servizi/tributi-finanze-e-contravvenzioni"

# Torino (001272): big-city showcase; category pages are flat, many services.
_TO = "comune.torino.it"
_TO_INDEX = f"https://{_TO}/servizi"
_TO_ANAG = f"https://{_TO}/servizi/anagrafe-stato-civile"
_TO_TRIB = f"https://{_TO}/servizi/tributi-finanze-contravvenzioni"

# Almè (016005): showcase whose category page is JS-rendered (no service-links).
_AL = "comune.alme.bg.it"
_AL_INDEX = f"https://{_AL}/servizi"
_AL_ANAG = f"https://{_AL}/servizi/anagrafe-e-stato-civile"

# Monsummano Terme (047009): tile-less paginated index (4 pages).
_MO = "comune.monsummano-terme.pt.it"
_MO_INDEX = f"https://{_MO}/servizi"

# Padova (028060): tile-less index with no static service-links → honest miss.
_PD = "comune.padova.it"
_PD_INDEX = f"https://{_PD}/servizi"


def _pagine_dicomano() -> dict[str, str]:
    return {
        _DIC_INDEX: _fix("048013_servizi_p0.html"),
        _DIC_ANAG: _fix("048013_cat_anagrafe-e-stato-civile_p0.html"),
        _DIC_TRIB: _fix("048013_cat_tributi-finanze-e-contravvenzioni_p0.html"),
    }


def _pagine_torino() -> dict[str, str]:
    return {
        _TO_INDEX: _fix("001272_servizi_p0.html"),
        _TO_ANAG: _fix("001272_cat_anagrafe-stato-civile_p0.html"),
        _TO_TRIB: _fix("001272_cat_tributi-finanze-contravvenzioni_p0.html"),
    }


def _pagine_alme() -> dict[str, str]:
    return {
        _AL_INDEX: _fix("016005_servizi_p0.html"),
        _AL_ANAG: _fix("016005_cat_anagrafe-e-stato-civile_p0.html"),
    }


def _pagine_monsummano() -> dict[str, str]:
    pagine = {_MO_INDEX: _fix("047009_servizi_p0.html")}
    for n in range(1, 4):  # p1..p3 → /servizi?page=N
        pagine[f"{_MO_INDEX}?page={n}"] = _fix(f"047009_servizi_p{n}.html")
    return pagine


# ── supports() — platform barrier ───────────────────────────────────────────


def test_supports_true_for_drupal_services_ordinary_data():
    req = _request(source_id="048013", service_key=ServiceKey.CARTA_IDENTITA)
    assert _connector({}).supports(req, platform_id="drupal") is True


def test_supports_false_for_non_drupal_platform():
    req = _request(source_id="048013", service_key=ServiceKey.CARTA_IDENTITA)
    assert _connector({}).supports(req, platform_id="comweb") is False


def test_supports_false_for_service_portal_surface():
    req = _request(
        source_id="048013",
        service_key=ServiceKey.CARTA_IDENTITA,
        surface=Surface.SERVICE_PORTAL,
    )
    assert _connector({}).supports(req, platform_id="drupal") is False


# ── mapping contract ────────────────────────────────────────────────────────


def test_argomento_mapping_covers_the_closed_vocabulary():
    # Total over ServiceKey: a new key without an argomento would silently resolve
    # to NOT_FOUND instead of a maintained honest miss.
    assert set(DRUPAL_BI_ARGOMENTO) == set(ServiceKey)


# ── _DrupalBiDiscovery — bounded scrape, both layouts ───────────────────────


def test_drill_collects_nested_service_links_never_tiles():
    # Small-comune category page nests services under the topic; every candidate
    # carries the service-link token, the id is the LAST path segment, and no
    # single-segment topic tile leaks in as a candidate.
    got = _DrupalBiDiscovery().scopri_servizi(
        _FetcherDrupal(_pagine_dicomano()).transport,
        base_url=_DIC_INDEX,
        term=ServiceKey.CARTA_IDENTITA.value,  # → argomento "anagrafe"
        limit=2000,
    )
    assert got  # the anagrafe category is not empty
    for c in got:
        path = str(c.url).split(f"https://{_DIC}", 1)[1]
        assert path.startswith("/servizi/anagrafe-e-stato-civile/")  # nested
        assert c.native_id == path.rstrip("/").rsplit("/", 1)[1]  # last segment


def test_discovery_follows_index_then_the_mapped_category_only():
    f = _FetcherDrupal(_pagine_dicomano())
    f.scopri_servizi(base_url=_DIC_INDEX, term=ServiceKey.TRIBUTI_IMU.value, limit=2000)
    # A tributi key drives the drill to the tributi category, never anagrafe.
    assert f.transport.letti[0] == _DIC_INDEX
    assert _DIC_TRIB in f.transport.letti
    assert _DIC_ANAG not in f.transport.letti


def test_offhost_service_anchor_is_dropped():
    # An anchor pointing off the comune host must never become a candidate (I-5),
    # even bearing the service-link token and a plausible path.
    veleno = (
        '<a data-element="service-link" '
        'href="https://evil.example/servizi/anagrafe/carta-d-identita">'
        "<span>Carta d'identità</span></a>"
    )
    visti: set[str] = set()
    cand: list = []
    _DrupalBiDiscovery._raccogli_servizi(veleno, _DIC_ANAG, _DIC, 2000, visti, cand)
    assert cand == []


# ── retrieve() — showcase drill ─────────────────────────────────────────────


def test_dicomano_carta_identita_single_confirmed_fulfilled():
    result = _connector(_pagine_dicomano()).retrieve(
        _request(source_id="048013", service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat="048013", host=_DIC),
        esito=None,
    )
    assert result.status is DataStatus.FULFILLED
    (ref,) = result.service_references
    assert ref.provider_platform == "drupal"
    # Id from the URL path segment, not the human title.
    assert "carta" in ref.service_id.lower()
    assert "Carta d'identità" not in ref.service_id
    assert ref.options[0].mode is ServiceAccessMode.INFORMATION


def test_dicomano_tributi_imu_single_confirmed_fulfilled():
    result = _connector(_pagine_dicomano()).retrieve(
        _request(source_id="048013", service_key=ServiceKey.TRIBUTI_IMU),
        mappa=_mappa(istat="048013", host=_DIC),
        esito=None,
    )
    assert result.status is DataStatus.FULFILLED
    (ref,) = result.service_references
    assert "imu" in ref.service_id.lower()


def test_dicomano_absent_key_is_honest_miss():
    # Dicomano's anagrafe category has no distinct cambio-residenza service the
    # recogniser confirms → 0 confirmed → NOT_FOUND (honest, not fabricated).
    result = _connector(_pagine_dicomano()).retrieve(
        _request(source_id="048013", service_key=ServiceKey.CAMBIO_RESIDENZA),
        mappa=_mappa(istat="048013", host=_DIC),
        esito=None,
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


def test_torino_big_city_ambiguous_is_not_found():
    # Torino's tributi category confirms ten IMU services → ≥2 → NOT_FOUND, never
    # an implicit pick (I-1).  Correct honest behaviour for a large comune.
    result = _connector(_pagine_torino()).retrieve(
        _request(source_id="001272", service_key=ServiceKey.TRIBUTI_IMU),
        mappa=_mappa(istat="001272", host=_TO),
        esito=None,
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


def test_alme_js_rendered_category_is_honest_miss():
    # Almè's category page is JS-rendered: it carries topic tiles but zero
    # server-side service-links → no candidate → NOT_FOUND.  No path is fabricated.
    result = _connector(_pagine_alme()).retrieve(
        _request(source_id="016005", service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat="016005", host=_AL),
        esito=None,
    )
    assert result.status is DataStatus.NOT_FOUND


# ── retrieve() — paginated-index fallback ───────────────────────────────────


def test_monsummano_fallback_paginates_index_and_fulfils():
    f = _FetcherDrupal(_pagine_monsummano())
    result = DrupalBiServiceConnector(f).retrieve(
        _request(source_id="047009", service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat="047009", host=_MO),
        esito=None,
    )
    # No tile on the index → fell back to paginating /servizi?page=N …
    assert f"{_MO_INDEX}?page=1" in f.transport.letti
    # … and the single confirmed carta service across the pages resolves.
    assert result.status is DataStatus.FULFILLED
    (ref,) = result.service_references
    assert ref.provider_platform == "drupal"


def test_monsummano_ambiguous_key_is_not_found():
    # accesso_atti matches two services across the paginated index → NOT_FOUND.
    result = _connector(_pagine_monsummano()).retrieve(
        _request(source_id="047009", service_key=ServiceKey.ACCESSO_ATTI),
        mappa=_mappa(istat="047009", host=_MO),
        esito=None,
    )
    assert result.status is DataStatus.NOT_FOUND


def test_padova_static_index_without_services_is_honest_miss():
    result = _connector({_PD_INDEX: _fix("028060_servizi_p0.html")}).retrieve(
        _request(source_id="028060", service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat="028060", host=_PD),
        esito=None,
    )
    assert result.status is DataStatus.NOT_FOUND


# ── retrieve() — request-shape guards ───────────────────────────────────────


def test_no_site_is_not_supported():
    result = _connector(_pagine_dicomano()).retrieve(
        _request(source_id="048013", service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat="048013", host=_DIC, sito=None),
        esito=None,
    )
    assert result.status is DataStatus.NOT_SUPPORTED


def test_missing_service_key_is_not_found():
    result = _connector(_pagine_dicomano()).retrieve(
        _request(source_id="048013", service_key=None),
        mappa=_mappa(istat="048013", host=_DIC),
        esito=None,
    )
    assert result.status is DataStatus.NOT_FOUND
