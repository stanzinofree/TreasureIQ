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

from pathlib import Path

import httpx
import pytest

from treasureiq.catalog.contracts import AccessMode, CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import (
    DataRequest,
    DataStatus,
    FreshnessPolicy,
)
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.wordpress_agid import (
    HttpxServiceFetcher,
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

    Records the last ``scopri_servizi`` term so a test can assert the connector
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

    def scopri_servizi(self, *, base_url, term, limit):
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
    return ServiceCandidate(native_id=str(wid), title=title, url=url)


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


def test_retrieve_rejects_rest_candidate_on_external_host():
    # The REST payload confirms the key by title but points at an external host:
    # it must be dropped, never become a source_url or an INFORMATION option.
    fetcher = StubFetcher(
        candidati=(
            _candidato(1, "Carta d'identità elettronica", url="https://evil.example/cie/"),
        )
    )
    c = _connector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()
    # The page for an off-host candidate is never even read.
    assert fetcher.pagine_lette == []


def test_retrieve_apex_candidate_accepted_against_www_official_host():
    # The REST permalink is on the apex, the mappa site keeps www: same comune.
    url = "https://comune.albano.rm.it/servizi/cie/"
    fetcher = StubFetcher(candidati=(_candidato(1, "Carta d'identità", url=url),))
    c = _connector(fetcher)
    result = c.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.FULFILLED
    assert str(result.service_references[0].source_url) == url


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


def test_page_scarta_boilerplate_tiene_modulo_cie():
    # Fix C (Slice 5.2): su Albano la pagina CIE linkava anche il boilerplate
    # del sito (cookie policy, termini e condizioni). Il modulo vero resta,
    # cornice fuori — giudicato sul NOME del link, non sul filename.
    html = (
        f'<a href="https://{_BASE}/wp-content/uploads/modulo-cie.pdf">Modulo richiesta CIE</a>'
        f'<a href="https://{_BASE}/wp-content/uploads/Cookie-Policy-2.pdf">Cookie policy</a>'
        f'<a href="https://{_BASE}/wp-content/uploads/Termini-e-Condizioni-Di-Servizio.pdf">'
        f'Termini e condizioni di servizio</a>'
    )
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/servizi/cie/", official_host=_BASE)
    urls = [str(l.url) for l in pagina.links if l.kind is EvidenceKind.DOWNLOAD]
    assert urls == [f"https://{_BASE}/wp-content/uploads/modulo-cie.pdf"]


def test_page_boilerplate_giudicato_dal_nome_non_dal_filename():
    # Il boilerplate si giudica sul NOME del link, mai sul filename: bare
    # "accessibilità" dentro il nome di un modulo vero NON è boilerplate (resta),
    # "note legali" lo è (cade) — anche con la stessa estensione .pdf.
    html = (
        f'<a href="https://{_BASE}/a.pdf">Modulo abbattimento barriere accessibilità edifici</a>'
        f'<a href="https://{_BASE}/b.pdf">Note legali</a>'
    )
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/s/", official_host=_BASE)
    kept = [str(l.url) for l in pagina.links if l.kind is EvidenceKind.DOWNLOAD]
    assert f"https://{_BASE}/a.pdf" in kept
    assert f"https://{_BASE}/b.pdf" not in kept


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


def test_page_online_phrase_in_other_block_is_not_evidence():
    # The "servizio online" phrase lives in its own paragraph; the generic link
    # is in a DIFFERENT block and must NOT inherit that evidence.
    html = (
        "<p>Puoi anche usare il servizio online del comune.</p>"
        '<div class="menu"><a href="https://area.comune.it/">Area personale</a></div>'
    )
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/s/", official_host=_BASE)
    assert pagina.links == ()


def test_page_evidence_from_aria_label_attribute():
    html = (
        '<a href="https://albano.urbi.it/portale" aria-label="Accedi al servizio online">'
        "Vai</a>"
    )
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/s/", official_host=_BASE)
    assert len(pagina.links) == 1
    assert pagina.links[0].kind is EvidenceKind.AUTHENTICATED_ONLINE


def test_page_online_phrase_in_same_container_is_evidence():
    html = (
        '<p>Presenta la domanda online: '
        '<a href="https://albano.urbi.it/portale">Accedi al servizio</a></p>'
    )
    pagina = leggi_pagina_servizio(html, page_url=f"https://{_BASE}/s/", official_host=_BASE)
    assert len(pagina.links) == 1
    assert pagina.links[0].kind is EvidenceKind.AUTHENTICATED_ONLINE


# ── HttpxServiceFetcher — the real HTTP boundary (net-free via MockTransport) ─

_OFFICIAL = "www.comune.albano.rm.it"
_PAGE = f"https://{_OFFICIAL}/servizi/cie/"


def _fetcher_with(handler) -> HttpxServiceFetcher:
    return HttpxServiceFetcher(transport=httpx.MockTransport(handler))


def test_fetcher_reads_page_on_official_host():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>ok</html>")

    assert _fetcher_with(handler).leggi_pagina(url=_PAGE, official_host=_OFFICIAL) == "<html>ok</html>"


def test_fetcher_rejects_redirect_to_external_host():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _OFFICIAL:
            return httpx.Response(302, headers={"location": "https://evil.example/steal"})
        # If the guard failed, this external body would leak through.
        return httpx.Response(200, text="<html>LEAKED</html>")

    assert _fetcher_with(handler).leggi_pagina(url=_PAGE, official_host=_OFFICIAL) is None


def test_fetcher_follows_same_comune_redirect_www_to_apex():
    apex = "comune.albano.rm.it"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _OFFICIAL:
            return httpx.Response(301, headers={"location": f"https://{apex}/servizi/cie/"})
        return httpx.Response(200, text="<html>apex</html>")

    assert _fetcher_with(handler).leggi_pagina(url=_PAGE, official_host=_OFFICIAL) == "<html>apex</html>"


def test_fetcher_rejects_initial_url_off_host():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>should-not-be-fetched</html>")

    result = _fetcher_with(handler).leggi_pagina(
        url="https://evil.example/cie/", official_host=_OFFICIAL
    )
    assert result is None


def test_fetcher_non_200_is_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    assert _fetcher_with(handler).leggi_pagina(url=_PAGE, official_host=_OFFICIAL) is None


# ── scopri_servizi — same redirect discipline on the REST read ───────────────

_BASE_URL = f"https://{_OFFICIAL}"
#: The REST collection entry the connector composes (rest_base folded in): the
#: neutral fetcher receives it as ``base_url``, never a bare ``rest_base``.
_REST_ENTRY = f"{_BASE_URL}/wp-json/wp/v2/servizi"
_REST_JSON = [{"id": 7, "title": {"rendered": "Carta d'identità"}, "link": f"{_BASE_URL}/servizi/cie/"}]


def _cerca(handler):
    return _fetcher_with(handler).scopri_servizi(
        base_url=_REST_ENTRY, term="carta d'identità", limit=20
    )


def test_fetcher_search_reads_official_host():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_REST_JSON)

    got = _cerca(handler)
    assert len(got) == 1 and got[0].native_id == "7"


def test_fetcher_search_rejects_redirect_to_external_host():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _OFFICIAL:
            return httpx.Response(302, headers={"location": "https://evil.example/wp-json/wp/v2/servizi"})
        # If the guard failed, this external JSON would be read as candidates.
        return httpx.Response(200, json=_REST_JSON)

    assert _cerca(handler) == ()


def test_fetcher_search_follows_same_comune_redirect_www_to_apex():
    apex = "comune.albano.rm.it"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _OFFICIAL:
            return httpx.Response(
                301, headers={"location": f"https://{apex}/wp-json/wp/v2/servizi"}
            )
        return httpx.Response(200, json=_REST_JSON)

    got = _cerca(handler)
    assert len(got) == 1 and got[0].native_id == "7"


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


# ── fixture-driven golden tests — real endpoint bytes, zero network ──────────
#
# The REST payloads below were captured live (2026-08) from real WP/AgID
# comuni.  The full pipeline runs on the recorded BYTES: MockTransport serves
# the fixture, HttpxServiceFetcher parses it, the connector confirms — so the
# four honest outcomes (FULFILLED / empty / single-non-confirming / noisy
# multi) are proven on ground truth, not on hand-written candidates.

_FIXTURES = Path(__file__).parent / "fixtures" / "wordpress_agid"

_ARONA_ISTAT = "003006"
_ARONA_HOST = "comune.arona.no.it"
_SAINTMARCEL_ISTAT = "007060"
_SAINTMARCEL_HOST = "comune.saintmarcel.ao.it"


class _TransportFixture:
    """MockTransport handler: real fixture bytes for the REST search, 404 for
    any page read.  Records every request for exact-form asserts."""

    def __init__(self, corpo: bytes) -> None:
        self._corpo = corpo
        self.richieste: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.richieste.append(request)
        if request.url.path.startswith("/wp-json/wp/v2/"):
            return httpx.Response(
                200, content=self._corpo, headers={"content-type": "application/json"}
            )
        return httpx.Response(404)

    @property
    def richieste_rest(self) -> list[httpx.Request]:
        return [r for r in self.richieste if r.url.path.startswith("/wp-json/wp/v2/")]


def _mappa_comune(istat: str, host: str) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=istat,
        nome=host,
        sito=host,
        sondato_il="2026-08-23T00:00:00+00:00",
        piattaforma_id="wordpress_agid",
        servizi=AssetServizi(esposto=True, rest_base="servizi", totale=42),
    )


def _retrieve_da_fixture(
    nome: str, *, istat: str, host: str, service_key: ServiceKey
) -> tuple[object, _TransportFixture]:
    transport = _TransportFixture((_FIXTURES / nome).read_bytes())
    connector = WordPressAgidServiceConnector(
        HttpxServiceFetcher(transport=httpx.MockTransport(transport))
    )
    request = _request(source_id=istat, service_key=service_key)
    result = connector.retrieve(request, mappa=_mappa_comune(istat, host), esito=None)
    return result, transport


def test_fixture_arona_carta_identita_is_fulfilled():
    # n=1 "Rilascio carta d'identità elettronica (CIE)" → confirmed → FULFILLED.
    result, _ = _retrieve_da_fixture(
        "arona_carta_identita.json",
        istat=_ARONA_ISTAT,
        host=_ARONA_HOST,
        service_key=ServiceKey.CARTA_IDENTITA,
    )
    assert result.status is DataStatus.FULFILLED
    assert result.access_mode is AccessMode.MEDIATED
    assert len(result.service_references) == 1
    ref = result.service_references[0]
    # Identity from the real WP id (1084 in the recorded payload), never the title.
    assert ref.service_id == f"{_ARONA_ISTAT}:wp:1084"
    assert str(ref.source_url) == (
        f"https://{_ARONA_HOST}/servizio/rilascio-carta-didentita-elettronica-cie/"
    )
    # Page read 404s in this transport → honest INFORMATION-only options.
    assert [o.mode for o in ref.options] == [ServiceAccessMode.INFORMATION]


def test_fixture_borgaro_entity_dotted_cie_now_confirms():
    # REAL payload: "Carta d&#8217;identità elettronica (C.I.E)" — HTML entity
    # apostrophe AND dotted "C.I.E" (no bare "CIE" token).  Before the shared
    # normalizer this was a FALSE NOT_FOUND (substring failed on the entity, the
    # word marker failed on the dots).  html.unescape + apostrophe fold in the
    # recogniser make the "carta d'identità" substring confirm → FULFILLED.
    result, _ = _retrieve_da_fixture(
        "borgaro_carta_identita.json",
        istat="001028",
        host="www.comune.borgaro-torinese.to.it",
        service_key=ServiceKey.CARTA_IDENTITA,
    )
    assert result.status is DataStatus.FULFILLED
    assert len(result.service_references) == 1
    ref = result.service_references[0]
    assert ref.service_id == "001028:wp:10911"
    assert str(ref.source_url) == (
        "https://www.comune.borgaro-torinese.to.it"
        "/servizio/carta-didentita-elettronica-c-i-e/"
    )


def test_fixture_lesa_entity_no_cie_token_now_confirms():
    # REAL payload: "Essere Cittadino &#8211; Carta d&#8217;Identità" — entity
    # en-dash + entity apostrophe, and NO CIE token at all.  Pre-fix this had no
    # path to confirm (Arona only slipped through on its "(CIE)" token); the
    # normalizer makes the "carta d'identità" substring the confirming path.
    result, _ = _retrieve_da_fixture(
        "lesa_carta_identita.json",
        istat="003084",
        host="www.comune.lesa.no.it",
        service_key=ServiceKey.CARTA_IDENTITA,
    )
    assert result.status is DataStatus.FULFILLED
    assert len(result.service_references) == 1
    ref = result.service_references[0]
    assert ref.service_id == "003084:wp:467"
    assert str(ref.source_url) == (
        "https://www.comune.lesa.no.it/servizio/essere-cittadino-carta-didentita/"
    )


def test_fixture_request_form_is_the_contract():
    # Exactly ONE REST GET, with the frozen shape:
    #   {site}/wp-json/wp/v2/servizi?search=<canonical term>&per_page=20&_fields=id,title,link
    _, transport = _retrieve_da_fixture(
        "arona_carta_identita.json",
        istat=_ARONA_ISTAT,
        host=_ARONA_HOST,
        service_key=ServiceKey.CARTA_IDENTITA,
    )
    assert len(transport.richieste_rest) == 1
    rest = transport.richieste_rest[0]
    assert rest.url.scheme == "https"
    assert rest.url.host == _ARONA_HOST
    assert rest.url.path == "/wp-json/wp/v2/servizi"
    assert rest.url.params["search"] == SERVICE_SEARCH_TERM[ServiceKey.CARTA_IDENTITA]
    assert rest.url.params["per_page"] == "20"
    assert rest.url.params["_fields"] == "id,title,link"


def test_fixture_saintmarcel_empty_payload_is_not_found():
    # A genuine `[]` from the live endpoint: honest miss, no page ever read.
    result, transport = _retrieve_da_fixture(
        "saintmarcel_carta_empty.json",
        istat=_SAINTMARCEL_ISTAT,
        host=_SAINTMARCEL_HOST,
        service_key=ServiceKey.CARTA_IDENTITA,
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.access_mode is AccessMode.MEDIATED
    assert result.service_references == ()
    assert transport.richieste == transport.richieste_rest  # only the search ran


def test_fixture_saintmarcel_single_non_confirming_is_not_found():
    # n=1 "Certificati anagrafici" for STATO_CIVILE: the recogniser does not
    # confirm it, and the near-miss is never picked — honest NOT_FOUND.
    result, transport = _retrieve_da_fixture(
        "saintmarcel_statocivile_single.json",
        istat=_SAINTMARCEL_ISTAT,
        host=_SAINTMARCEL_HOST,
        service_key=ServiceKey.STATO_CIVILE,
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()
    # An unconfirmed candidate's page is never even read.
    assert transport.richieste == transport.richieste_rest


def test_fixture_arona_residenza_multi_is_not_found():
    # >1 noisy candidates ("Affidamento ceneri", "Cambio nome e cognome",
    # "Cambio e dichiarazione di residenza"): none confirms CAMBIO_RESIDENZA
    # under the shared recogniser — honest NOT_FOUND, never the nearest title.
    result, transport = _retrieve_da_fixture(
        "arona_residenza_multi.json",
        istat=_ARONA_ISTAT,
        host=_ARONA_HOST,
        service_key=ServiceKey.CAMBIO_RESIDENZA,
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()
    assert transport.richieste == transport.richieste_rest


def test_fixture_albaredo_dialetto_b_reads_as_false_empty():
    # KNOWN CLASSIFICATION DEFECT, asserted as today's behaviour: Albaredo
    # d'Adige serves the same Design Comuni theme through a CUSTOM REST
    # controller (dialect B) — items carry "ID"/"post_title" and direct AgID
    # fields, no "id"/"title.rendered"/"link".  The A-standard parser yields 0
    # candidates from a payload that IS full of services (e.g. "Calcolo IMU
    # online"): the miss below is a false empty, not a real one.  Fixing it
    # needs a dedicated dialect-B connector, not a looser parser here — 0/≥2
    # stay an honest miss by contract.
    result, transport = _retrieve_da_fixture(
        "albaredo_dialettoB_raw.json",
        istat="023002",
        host="www.comune.albaredodadige.vr.it",
        service_key=ServiceKey.TRIBUTI,
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()
    # The search ran (one REST GET) and nothing else: the payload's items were
    # all dropped by the standard-shape parser.
    assert len(transport.richieste_rest) == 1
    assert transport.richieste == transport.richieste_rest
