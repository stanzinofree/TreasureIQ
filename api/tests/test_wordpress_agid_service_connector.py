"""Golden tests for the WordPress/AgID pilot service connector (Ramo 3, Slice 4).

Net-free: the network is behind the injected ``ServiceFetcher``.  Three layers
are exercised:

- the connector's ``supports``/``retrieve`` contract (single-confirmed →
  ServiceReference; 0/≥2 → NOT_FOUND; identity from the WP id, never the title);
- ``leggi_pagina_servizio`` provenance policy (same-host PDF, external auth,
  the rejections);
- the shared recogniser re-run on realistic WordPress service titles.
"""

from __future__ import annotations

import pytest

from treasureiq.catalog.contracts import AccessMode, CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import (
    DataRequest,
    DataStatus,
    FreshnessPolicy,
)
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.wordpress_agid import (
    WordPressAgidServiceConnector,
)
from treasureiq.catalog.service_contracts import (
    SERVICE_SEARCH_TERM,
    AuthenticationMethod,
    ServiceAccessMode,
    ServiceKey,
)
from treasureiq.catalog.service_page import EvidenceKind, leggi_pagina_servizio
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

_ISTAT = "058003"
_BASE = "www.comune.albano.rm.it"


# ── fixtures / doubles ──────────────────────────────────────────────────────


class StubFetcher:
    """A ``ServiceFetcher`` returning canned candidates and page HTML.

    Records the last ``cerca_servizi`` term so a test can assert the connector
    drove the query with the canonical term."""

    def __init__(
        self,
        *,
        candidati: tuple[ServiceCandidate, ...] = (),
        pagine: dict[str, str] | None = None,
    ) -> None:
        self._candidati = candidati
        self._pagine = pagine or {}
        self.ultimo_term: str | None = None
        self.pagine_lette: list[str] = []

    def cerca_servizi(self, *, base_url, rest_base, term, limit):
        self.ultimo_term = term
        return self._candidati

    def leggi_pagina(self, *, url, official_host):
        self.pagine_lette.append(url)
        return self._pagine.get(url)


def _mappa(*, sito: str | None = _BASE, esposto: bool = True) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=_ISTAT,
        nome="Albano Laziale",
        sito=sito,
        sondato_il="2026-08-23T00:00:00+00:00",
        piattaforma_id="wordpress_agid",
        servizi=AssetServizi(esposto=esposto, rest_base="servizi", totale=42),
    )


def _request(
    *,
    source_id: str = _ISTAT,
    service_key: ServiceKey | str | None = ServiceKey.CARTA_IDENTITA,
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


def _connector(fetcher: StubFetcher) -> WordPressAgidServiceConnector:
    return WordPressAgidServiceConnector(fetcher)


def _candidato(
    wid: int, title: str, url: str = f"https://{_BASE}/servizi/carta-identita/"
) -> ServiceCandidate:
    return ServiceCandidate(wordpress_id=wid, title=title, url=url)


# ── supports() — the barrier of non-confusion ───────────────────────────────


def test_supports_true_for_wp_services_ordinary_data():
    c = _connector(StubFetcher())
    assert c.supports(_request(), platform_id="wordpress_agid") is True


def test_supports_false_for_service_portal_surface():
    c = _connector(StubFetcher())
    req = _request(surface=Surface.SERVICE_PORTAL)
    assert c.supports(req, platform_id="wordpress_agid") is False


def test_supports_false_for_other_capability():
    c = _connector(StubFetcher())
    req = _request(capability="offices")
    assert c.supports(req, platform_id="wordpress_agid") is False


def test_supports_false_for_non_wp_platform():
    c = _connector(StubFetcher())
    assert c.supports(_request(), platform_id="peopleweb") is False


# ── retrieve() — guards ─────────────────────────────────────────────────────


def test_retrieve_not_found_without_service_key():
    c = _connector(StubFetcher())
    result = c.retrieve(_request(service_key=None), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND
    assert result.access_mode is AccessMode.UNAVAILABLE
    assert result.service_references == ()


def test_retrieve_not_found_for_unknown_service_key_value():
    c = _connector(StubFetcher())
    result = c.retrieve(_request(service_key="passaporto"), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND


def test_retrieve_not_supported_without_site():
    c = _connector(StubFetcher())
    result = c.retrieve(_request(), mappa=_mappa(sito=None), esito=None)
    assert result.status is DataStatus.NOT_SUPPORTED
    assert result.access_mode is AccessMode.UNAVAILABLE


def test_retrieve_not_supported_when_services_not_exposed():
    c = _connector(StubFetcher())
    result = c.retrieve(_request(), mappa=_mappa(esposto=False), esito=None)
    assert result.status is DataStatus.NOT_SUPPORTED


def test_retrieve_raises_on_source_id_mismatch():
    c = _connector(StubFetcher())
    req = _request(source_id="058079")  # a different comune than the mappa
    with pytest.raises(ValueError):
        c.retrieve(req, mappa=_mappa(), esito=None)


# ── retrieve() — resolution ─────────────────────────────────────────────────


def test_retrieve_single_confirmed_builds_reference():
    fetcher = StubFetcher(
        candidati=(_candidato(1234, "Carta d'identità elettronica (CIE)"),)
    )
    c = _connector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)

    assert result.status is DataStatus.FULFILLED
    assert result.access_mode is AccessMode.MEDIATED
    assert len(result.service_references) == 1
    ref = result.service_references[0]
    # Identity from the WP id, never the title.
    assert ref.service_id == f"{_ISTAT}:wp:1234"
    assert str(ref.source_url) == f"https://{_BASE}/servizi/carta-identita/"
    # INFORMATION is always present.
    assert ref.options[0].mode is ServiceAccessMode.INFORMATION


def test_retrieve_drives_query_with_canonical_term():
    fetcher = StubFetcher(candidati=(_candidato(1, "Carta d'identità"),))
    c = _connector(fetcher)
    c.retrieve(_request(service_key=ServiceKey.CAMBIO_RESIDENZA), mappa=_mappa(), esito=None)
    assert fetcher.ultimo_term == SERVICE_SEARCH_TERM[ServiceKey.CAMBIO_RESIDENZA]


def test_retrieve_zero_confirmed_is_not_found():
    # The search returned something, but no title confirms the requested key.
    fetcher = StubFetcher(candidati=(_candidato(9, "Prenotazione appuntamenti URP"),))
    c = _connector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND
    assert result.access_mode is AccessMode.MEDIATED
    assert result.service_references == ()


def test_retrieve_two_confirmed_is_ambiguous_not_found():
    fetcher = StubFetcher(
        candidati=(
            _candidato(1, "Carta d'identità elettronica", url=f"https://{_BASE}/a/"),
            _candidato(2, "Carta di identità cartacea", url=f"https://{_BASE}/b/"),
        )
    )
    c = _connector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


def test_retrieve_unconfirmed_candidates_are_dropped_leaving_one():
    # Two candidates, only one confirms → exactly one, resolves.
    fetcher = StubFetcher(
        candidati=(
            _candidato(1, "Prenotazione appuntamenti", url=f"https://{_BASE}/a/"),
            _candidato(2, "Carta d'identità elettronica", url=f"https://{_BASE}/cie/"),
        )
    )
    c = _connector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.FULFILLED
    assert result.service_references[0].service_id == f"{_ISTAT}:wp:2"


def test_retrieve_page_unreadable_yields_only_information():
    fetcher = StubFetcher(
        candidati=(_candidato(1234, "Carta d'identità elettronica"),),
        pagine={},  # leggi_pagina returns None
    )
    c = _connector(fetcher)
    ref = c.retrieve(_request(), mappa=_mappa(), esito=None).service_references[0]
    assert [o.mode for o in ref.options] == [ServiceAccessMode.INFORMATION]


def test_retrieve_download_option_from_page_evidence():
    url = f"https://{_BASE}/servizi/carta-identita/"
    html = (
        f'<a href="/wp-content/uploads/modulo-cie.pdf">Scarica il modulo</a>'
    )
    fetcher = StubFetcher(candidati=(_candidato(1234, "Carta d'identità"),), pagine={url: html})
    c = _connector(fetcher)
    ref = c.retrieve(_request(), mappa=_mappa(), esito=None).service_references[0]
    modes = [o.mode for o in ref.options]
    assert ServiceAccessMode.DOWNLOAD in modes
    download = next(o for o in ref.options if o.mode is ServiceAccessMode.DOWNLOAD)
    assert str(download.url) == f"https://{_BASE}/wp-content/uploads/modulo-cie.pdf"
    # source_url stays the comune's official service page.
    assert str(download.source_url) == url


def test_retrieve_authenticated_option_external_host_allowed():
    url = f"https://{_BASE}/servizi/cambio-residenza/"
    html = (
        '<p>Presenta la domanda online con SPID: '
        '<a href="https://albano.urbi.it/portale/servizi">Accedi al servizio</a></p>'
    )
    fetcher = StubFetcher(
        candidati=(_candidato(77, "Cambio di residenza", url=url),),
        pagine={url: html},
    )
    c = _connector(fetcher)
    ref = c.retrieve(
        _request(service_key=ServiceKey.CAMBIO_RESIDENZA), mappa=_mappa(), esito=None
    ).service_references[0]
    auth = next(o for o in ref.options if o.mode is ServiceAccessMode.AUTHENTICATED_ONLINE)
    assert auth.requires_authentication is True
    assert str(auth.url).startswith("https://albano.urbi.it/")
    assert AuthenticationMethod.SPID in auth.authentication
    # Never followed nor authenticated: source_url is the comune's page.
    assert str(auth.source_url) == url


# ── leggi_pagina_servizio — provenance policy ───────────────────────────────


def test_page_download_same_host_only():
    html = (
        f'<a href="https://{_BASE}/files/a.pdf">interno</a>'
        f'<a href="https://altro-host.it/b.pdf">esterno</a>'
    )
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/s/", official_host=_BASE)
    kinds = [(l.kind, str(l.url)) for l in pagina.links]
    assert (EvidenceKind.DOWNLOAD, f"https://{_BASE}/files/a.pdf") in kinds
    assert all("altro-host.it" not in u for _, u in kinds)


def test_page_bare_area_personale_is_not_evidence():
    html = '<a href="https://area.comune.it/">Area personale</a>'
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/s/", official_host=_BASE)
    assert pagina.links == ()


def test_page_rejects_non_http_and_fragment():
    html = (
        '<a href="javascript:void(0)">x</a>'
        '<a href="mailto:info@comune.it">mail</a>'
        '<a href="#section">ancora</a>'
    )
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/s/", official_host=_BASE)
    assert pagina.links == ()


def test_page_resolves_relative_download():
    html = '<a href="modulo.pdf">Modulo</a>'
    pagina = leggi_pagina_servizio(
        html, page_url=f"https://{_BASE}/servizi/cie/", official_host=_BASE
    )
    assert str(pagina.links[0].url) == f"https://{_BASE}/servizi/cie/modulo.pdf"


def test_page_dedup_same_url_and_kind():
    html = (
        f'<a href="https://{_BASE}/m.pdf">Scarica</a>'
        f'<a href="https://{_BASE}/m.pdf">Scarica di nuovo</a>'
    )
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/s/", official_host=_BASE)
    assert len(pagina.links) == 1


# ── recogniser re-run on WordPress service titles ───────────────────────────


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Carta d'identità elettronica (CIE)", ServiceKey.CARTA_IDENTITA),
        ("Cambio di residenza", ServiceKey.CAMBIO_RESIDENZA),
        ("Accesso agli atti amministrativi", ServiceKey.ACCESSO_ATTI),
        ("Certificato di nascita (stato civile)", ServiceKey.STATO_CIVILE),
        ("Pagamento tributi comunali (IMU/TARI)", ServiceKey.TRIBUTI),
    ],
)
def test_recognizer_on_wordpress_titles(title, expected):
    assert riconosci_service_key(title) is expected


def test_recognizer_on_ambiguous_title_is_none():
    # A title marking two distinct keys must not be forced to one.
    assert riconosci_service_key("Carta d'identità e cambio di residenza") is None


def test_recognizer_on_unrelated_title_is_none():
    assert riconosci_service_key("Prenotazione appuntamenti allo sportello") is None
