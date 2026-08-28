"""Golden tests for the ComWeb service connector (Ramo 3, Connettore #2).

Net-free: the network is behind a stub transport serving captured fixtures.  Two
layers are exercised:

- ``_ComWebDiscovery`` — bounded scrape (index → one category page → scheda
  anchors) against the real Alpignano fixtures: the showcase index carries no
  anagrafe schede, the category page carries them all, categories are never
  candidates, off-host anchors are dropped, an unmapped category fabricates no
  URL;
- ``ComWebServiceConnector`` — the shared ``retrieve`` contract wired to real
  discovery: single-confirmed → ServiceReference with the ``:comweb:`` id, ≥2 →
  NOT_FOUND, the ``servizi.esposto=False`` gate still resolves (§3.4), identity
  from the scheda path, never the title.
"""

from __future__ import annotations

from pathlib import Path

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, AccessMode, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.service_connectors.comweb_service import (
    _CAP_DIFENSIVO_SCHEDE,
    COMWEB_SERVICE_CATEGORY,
    ComWebServiceConnector,
    _ComWebDiscovery,
)
from treasureiq.catalog.service_contracts import ServiceAccessMode, ServiceKey
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

_ISTAT = "001008"
_HOST = "www.comune.alpignano.to.it"
_BASE = f"https://{_HOST}"
_INDEX = f"{_BASE}/it-it/servizi"
_CAT_ANAGRAFE = f"{_BASE}/it-it/servizi/anagrafe-e-stato-civile"
_CAT_TRIBUTI = f"{_BASE}/it-it/servizi/tributi-finanze-e-contravvenzioni"

_FIXTURES = Path(__file__).parent / "fixtures"


def _fix(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


_INDICE_HTML = _fix("comweb_servizi_alpignano.html")
_ANAGRAFE_HTML = _fix("comweb_categoria_anagrafe_alpignano.html")
_TRIBUTI_HTML = _fix("comweb_categoria_tributi_alpignano.html")


# ── doubles ─────────────────────────────────────────────────────────────────


class _StubTransport:
    """Serves canned HTML per-URL; records what was fetched."""

    def __init__(self, pagine: dict[str, str]) -> None:
        self._pagine = pagine
        self.letti: list[str] = []

    def leggi_pagina(self, *, url, official_host):
        self.letti.append(url)
        return self._pagine.get(url)


class _FetcherComweb:
    """Real ``_ComWebDiscovery`` over a stub transport → a ``ServiceFetcher``.

    Wiring the real discovery (not canned candidates) means the connector tests
    exercise the scrape + recogniser end-to-end, net-free."""

    def __init__(self, pagine: dict[str, str]) -> None:
        self.transport = _StubTransport(pagine)
        self._discovery = _ComWebDiscovery()

    def scopri_servizi(self, *, base_url, term, limit):
        return self._discovery.scopri_servizi(
            self.transport, base_url=base_url, term=term, limit=limit
        )

    def leggi_pagina(self, *, url, official_host):
        return self.transport.leggi_pagina(url=url, official_host=official_host)


def _mappa(*, sito: str | None = _HOST, esposto: bool = False) -> MappaConnettore:
    # esposto defaults to False: ComWeb never exposes the WP-REST service CPT, and
    # the connector must resolve anyway (§3.4).
    return MappaConnettore(
        codice_istat=_ISTAT,
        nome="Alpignano",
        sito=sito,
        sondato_il="2026-08-23T00:00:00+00:00",
        piattaforma_id="comweb",
        servizi=AssetServizi(esposto=esposto, rest_base=None, totale=0),
    )


def _request(
    *,
    source_id: str = _ISTAT,
    service_key: ServiceKey | str | None = ServiceKey.CAMBIO_RESIDENZA,
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


def _pagine_reali() -> dict[str, str]:
    return {_INDEX: _INDICE_HTML, _CAT_ANAGRAFE: _ANAGRAFE_HTML, _CAT_TRIBUTI: _TRIBUTI_HTML}


def _connector(pagine: dict[str, str]) -> ComWebServiceConnector:
    return ComWebServiceConnector(_FetcherComweb(pagine))


# ── supports() — platform barrier ───────────────────────────────────────────


def test_supports_true_for_comweb_services_ordinary_data():
    assert _connector({}).supports(_request(), platform_id="comweb") is True


def test_supports_false_for_non_comweb_platform():
    assert _connector({}).supports(_request(), platform_id="wordpress_agid") is False


def test_supports_false_for_service_portal_surface():
    req = _request(surface=Surface.SERVICE_PORTAL)
    assert _connector({}).supports(req, platform_id="comweb") is False


# ── _ComWebDiscovery — bounded scrape ───────────────────────────────────────


def test_index_is_showcase_no_anagrafe_schede():
    # V-1: the index alone yields no anagrafe scheda for the anagrafe category —
    # it is a showcase.  Discovery must drill the category page to find them.
    solo_indice = _ComWebDiscovery()._schede(_INDICE_HTML, _INDEX, _HOST, 200)
    slug = "anagrafe-e-stato-civile"
    assert not any(f"/{slug}/" in str(c.url) for c in solo_indice)


def test_drill_category_collects_schede_never_categories():
    got = _ComWebDiscovery().scopri_servizi(
        _FetcherComweb(_pagine_reali()).transport,
        base_url=_INDEX,
        term=ServiceKey.CARTA_IDENTITA.value,  # thematic → anagrafe-e-stato-civile
        limit=200,
    )
    # Every candidate is a two-segment scheda (numeric id + hash), never a
    # single-segment category.
    assert len(got) == 56
    for c in got:
        path = str(c.url).split(_BASE, 1)[1]
        assert path.count("/") == 4  # /it-it/servizi/{cat}/{scheda}
        assert c.native_id and c.native_id[-32:].isalnum()


def test_discovery_follows_only_index_and_one_category():
    f = _FetcherComweb(_pagine_reali())
    f.scopri_servizi(base_url=_INDEX, term=ServiceKey.CARTA_IDENTITA.value, limit=200)
    # Exactly two page reads: the index, then the one mapped category.  No crawl.
    assert f.transport.letti == [_INDEX, _CAT_ANAGRAFE]


def test_unmapped_category_absent_from_index_no_fabricated_url():
    # An index whose only category is neither thematic nor life-event: schema
    # detection falls back to THEMATIC, the mapped category (anagrafe) is absent
    # from the anchors → discovery must NOT fabricate its URL: reads index, stops.
    indice_senza_mappata = (
        '<a href="/it-it/servizi/bandi-e-concorsi/">Bandi e concorsi</a>'
    )
    f = _FetcherComweb({_INDEX: indice_senza_mappata})
    got = f.scopri_servizi(
        base_url=_INDEX, term=ServiceKey.CARTA_IDENTITA.value, limit=200
    )
    assert got == ()
    assert f.transport.letti == [_INDEX]  # category page never fetched


def test_discovery_drops_off_host_scheda():
    html = (
        '<a href="https://evil.example/it-it/servizi/anagrafe/'
        'furto-1-2-3-00000000000000000000000000000000">Furto dati</a>'
        '<a href="/it-it/servizi/anagrafe/cambio-residenza-305-59428-1-'
        'ed80250a6bea88e349c3d678093f1e4f">Cambio Residenza</a>'
    )
    got = _ComWebDiscovery()._schede(html, _CAT_ANAGRAFE, _HOST, 200)
    assert len(got) == 1
    assert str(got[0].url).startswith(_BASE)  # only the on-host one survives


def test_discovery_limit_caps_fan_out():
    schede = "".join(
        f'<a href="/it-it/servizi/anagrafe/servizio-{i}-{i}-1-'
        f'{"a" * 32}">Servizio {i}</a>'
        for i in range(50)
    )
    got = _ComWebDiscovery()._schede(schede, _CAT_ANAGRAFE, _HOST, 3)
    assert len(got) == 3  # never more than limit


def _hex32(n: int) -> str:
    # A distinct 32-hex tail per scheda (so _RE_SCHEDA matches, ids don't collide).
    return f"{n:032x}"


def _categoria_lunga(match_at: int, totale: int) -> str:
    # A synthetic anagrafe category page: `totale` filler schede whose titles never
    # confirm any key, with the useful "Cambio Residenza" scheda at position
    # `match_at`.  Reproduces a long category (tributi-like) where the match falls
    # far down the page.
    righe = []
    for i in range(totale):
        if i == match_at:
            righe.append(
                '<a href="/it-it/servizi/anagrafe-e-stato-civile/'
                f'cambio-residenza-9-1-{_hex32(i)}">Cambio Residenza</a>'
            )
        else:
            righe.append(
                '<a href="/it-it/servizi/anagrafe-e-stato-civile/'
                f'servizio-generico-{i}-1-{_hex32(i)}">Servizio Generico {i}</a>'
            )
    return "".join(righe)


def test_cap_is_defensive_not_a_selection_limit():
    # The cap must sit far above any real municipal category so it never truncates
    # confirmations (anagrafe 56, tributi 16).
    assert _CAP_DIFENSIVO_SCHEDE >= 1000


def test_discovery_collects_all_schede_on_a_long_page():
    # A single category page with 250 schede — all collected (>> old 200 cap).
    html = _categoria_lunga(match_at=249, totale=250)
    got = _ComWebDiscovery()._schede(html, _CAT_ANAGRAFE, _HOST, _CAP_DIFENSIVO_SCHEDE)
    assert len(got) == 250


def test_match_beyond_old_limit_still_resolves():
    # P1 regression: the useful scheda at position 250 (beyond the old 200 cap)
    # must still resolve — the cap must not drop it before confirmation.
    lunga = _categoria_lunga(match_at=250, totale=300)
    pagine = {_INDEX: _INDICE_HTML, _CAT_ANAGRAFE: lunga}
    result = _connector(pagine).retrieve(
        _request(service_key=ServiceKey.CAMBIO_RESIDENZA), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.FULFILLED
    (ref,) = result.service_references
    assert ref.service_id.endswith(f"cambio-residenza-9-1-{_hex32(250)}")


# ── retrieve() — the shared contract on ComWeb ──────────────────────────────


def test_single_confirmed_yields_reference_with_comweb_id():
    result = _connector(_pagine_reali()).retrieve(
        _request(service_key=ServiceKey.CAMBIO_RESIDENZA), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.FULFILLED
    assert result.access_mode is AccessMode.MEDIATED
    (ref,) = result.service_references
    assert ref.service_id == (
        f"{_ISTAT}:comweb:cambio-residenza-305-59428-1-ed80250a6bea88e349c3d678093f1e4f"
    )
    assert ref.provider_platform == "comweb"
    # INFORMATION option is always the cited source page.
    assert ref.options[0].mode is ServiceAccessMode.INFORMATION


def test_service_id_from_path_never_from_title():
    result = _connector(_pagine_reali()).retrieve(
        _request(service_key=ServiceKey.CAMBIO_RESIDENZA), mappa=_mappa(), esito=None
    )
    (ref,) = result.service_references
    # The id is the scheda path segment; the (human) title is not inside it.
    assert "Cambio Residenza" not in ref.service_id
    assert ref.title == "Cambio Residenza"


def test_ambiguous_key_is_not_found():
    # carta_identita matches two schede (carta + CIE) → ambiguous → NOT_FOUND,
    # never an implicit pick (I-1).
    result = _connector(_pagine_reali()).retrieve(
        _request(service_key=ServiceKey.CARTA_IDENTITA), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


def test_tributi_follows_the_mapped_category():
    f = _FetcherComweb(_pagine_reali())
    ComWebServiceConnector(f).retrieve(
        _request(service_key=ServiceKey.TRIBUTI_IMU), mappa=_mappa(), esito=None
    )
    # A tributi sub-key drives the connector to the tributi category, not anagrafe.
    assert _CAT_TRIBUTI in f.transport.letti
    assert _CAT_ANAGRAFE not in f.transport.letti


def test_gate_proceeds_when_servizi_not_exposed():
    # servizi.esposto=False (always true on ComWeb) must NOT gate the connector
    # out — unlike the WP pilot (§3.4).
    result = _connector(_pagine_reali()).retrieve(
        _request(service_key=ServiceKey.CAMBIO_RESIDENZA),
        mappa=_mappa(esposto=False),
        esito=None,
    )
    assert result.status is DataStatus.FULFILLED


def test_no_site_is_not_supported():
    result = _connector(_pagine_reali()).retrieve(
        _request(service_key=ServiceKey.CAMBIO_RESIDENZA),
        mappa=_mappa(sito=None),
        esito=None,
    )
    assert result.status is DataStatus.NOT_SUPPORTED


def test_missing_service_key_is_not_found():
    result = _connector(_pagine_reali()).retrieve(
        _request(service_key=None), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.NOT_FOUND


def test_category_mapping_covers_the_closed_vocabulary():
    # The mapping must be total over ServiceKey: a new key without a category
    # would silently resolve to NOT_SUPPORTED.
    assert set(COMWEB_SERVICE_CATEGORY) == set(ServiceKey)


# ── Agliè (001001) — second real municipality, per-key ground truth ─────────
#
# A second captured portal proves the mapping against a different card set.
# Fixtures under fixtures/comweb/: index (9 categories), anagrafe category
# (16 cards), tributi category (9 cards).  Every outcome below is the REAL
# behaviour of the connector+recogniser on these cards — including the honest
# misses (0 or ≥2 confirmed → NOT_FOUND, never the nearest neighbour).

_ISTAT_AGLIE = "001001"
_HOST_AGLIE = "www.comune.aglie.to.it"
_BASE_AGLIE = f"https://{_HOST_AGLIE}"
_INDEX_AGLIE = f"{_BASE_AGLIE}/it-it/servizi"
_CAT_ANAGRAFE_AGLIE = f"{_BASE_AGLIE}/it-it/servizi/anagrafe-e-stato-civile"
_CAT_TRIBUTI_AGLIE = f"{_BASE_AGLIE}/it-it/servizi/tributi-finanze-e-contravvenzioni"

_INDICE_AGLIE_HTML = _fix("comweb/aglie_indice_servizi.html")
_ANAGRAFE_AGLIE_HTML = _fix("comweb/aglie_anagrafe_categoria.html")
_TRIBUTI_AGLIE_HTML = _fix("comweb/aglie_tributi_categoria.html")


def _pagine_aglie() -> dict[str, str]:
    return {
        _INDEX_AGLIE: _INDICE_AGLIE_HTML,
        _CAT_ANAGRAFE_AGLIE: _ANAGRAFE_AGLIE_HTML,
        _CAT_TRIBUTI_AGLIE: _TRIBUTI_AGLIE_HTML,
    }


def _mappa_aglie() -> MappaConnettore:
    return MappaConnettore(
        codice_istat=_ISTAT_AGLIE,
        nome="Agliè",
        sito=_HOST_AGLIE,
        sondato_il="2026-08-24T00:00:00+00:00",
        piattaforma_id="comweb",
        servizi=AssetServizi(esposto=False, rest_base=None, totale=0),
    )


def _retrieve_aglie(service_key: ServiceKey):
    f = _FetcherComweb(_pagine_aglie())
    result = ComWebServiceConnector(f).retrieve(
        _request(source_id=_ISTAT_AGLIE, service_key=service_key),
        mappa=_mappa_aglie(),
        esito=None,
    )
    return result, f.transport.letti


def test_aglie_cambio_residenza_single_card_fulfilled():
    # Exactly one anagrafe card confirms CAMBIO_RESIDENZA ("Cambio Residenza").
    result, letti = _retrieve_aglie(ServiceKey.CAMBIO_RESIDENZA)
    assert result.status is DataStatus.FULFILLED
    (ref,) = result.service_references
    assert ref.service_id == (
        f"{_ISTAT_AGLIE}:comweb:"
        "cambio-residenza-305-22801-1-f8ed806f0a9e480cb1bd70418787502c"
    )
    assert ref.title == "Cambio Residenza"
    # Request shape: index, then the ONE mapped category, then the scheda page
    # (options read).  No other category, no crawl.
    assert letti[:2] == [_INDEX_AGLIE, _CAT_ANAGRAFE_AGLIE]
    assert len(letti) == 3 and letti[2] == str(ref.source_url)


def test_aglie_accesso_atti_confirms_atti_never_accesso_civico():
    # The anagrafe category carries BOTH "Richiedere l'accesso agli atti" and
    # "Accesso Civico".  Only the former marks ACCESSO_ATTI; "Accesso Civico"
    # (a different institute) carries no marker and is never confirmed.
    result, _ = _retrieve_aglie(ServiceKey.ACCESSO_ATTI)
    assert result.status is DataStatus.FULFILLED
    (ref,) = result.service_references
    assert "richiedere-l-accesso-agli-atti" in ref.service_id
    assert "accesso-civico" not in ref.service_id
    assert ref.title == "Richiedere l'accesso agli atti"


def test_aglie_carta_identita_two_cards_honest_not_found():
    # Two cards confirm CARTA_IDENTITA — "Carta d'Identità Elettronica (CIE)"
    # and "Carta d'identità per minori" — so ≥2 confirmed → NOT_FOUND (I-1).
    # No card-derivable rule elects one as canonical: an "audience qualifier"
    # tie-break would be an arbitrary pick, not evidence.
    result, _ = _retrieve_aglie(ServiceKey.CARTA_IDENTITA)
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


def test_aglie_carta_identita_miss_is_two_confirmed_not_zero():
    # Prove the miss above is ambiguity (2 confirmed), not a recogniser blind
    # spot (0 confirmed): both CIE cards individually confirm the key.
    from treasureiq.chat.service_key import riconosci_service_key

    f = _FetcherComweb(_pagine_aglie())
    candidati = f.scopri_servizi(
        base_url=_INDEX_AGLIE,
        term=ServiceKey.CARTA_IDENTITA.value,  # aglie index = thematic → anagrafe
        limit=_CAP_DIFENSIVO_SCHEDE,
    )
    confermati = [
        c.title for c in candidati if riconosci_service_key(c.title) is ServiceKey.CARTA_IDENTITA
    ]
    assert sorted(confermati) == [
        "Carta d'Identità Elettronica (CIE)",
        "Carta d'identità per minori",
    ]


def test_aglie_stato_civile_is_honest_not_found():
    # REAL behaviour after the shared-recogniser fix: no Agliè card is titled
    # "stato civile" or carries an unambiguous civil-registry certificate
    # phrase.  The only near-hit, "Richiedere una pubblicazione di matrimonio"
    # (the banns), is a DISTINCT service and no longer confirms STATO_CIVILE —
    # bare "matrimonio" was dropped as a marker (see service_key.py).  Zero
    # confirmed candidates → honest NOT_FOUND, never the nearest card.
    result, _ = _retrieve_aglie(ServiceKey.STATO_CIVILE)
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


def test_aglie_tributi_imu_single_card_fulfilled():
    # After the TRIBUTI split, the tributi category's two tax cards resolve
    # cleanly per key instead of colliding into an ambiguous NOT_FOUND.
    # "Pagare tributi IMU" is the ONLY card confirming TRIBUTI_IMU (marker
    # "imu"); the TARI card does not → exactly one confirmed → FULFILLED.
    result, letti = _retrieve_aglie(ServiceKey.TRIBUTI_IMU)
    assert result.status is DataStatus.FULFILLED
    (ref,) = result.service_references
    assert ref.service_id == (
        f"{_ISTAT_AGLIE}:comweb:"
        "pagare-tributi-imu-600-22892-1-a3256eda7bd21d2164edd278345c061f"
    )
    assert ref.title == "Pagare tributi IMU"
    # Index → the ONE mapped (tributi) category → the scheda page. No anagrafe.
    assert letti[:2] == [_INDEX_AGLIE, _CAT_TRIBUTI_AGLIE]
    assert len(letti) == 3 and letti[2] == str(ref.source_url)


def test_aglie_tributi_tari_single_card_fulfilled():
    # "Pagamento Tassa Rifiuti (TARI)" is the ONLY card confirming TRIBUTI_TARI
    # (markers "tassa rifiuti"/"tari"); the IMU card does not → one confirmed →
    # FULFILLED.  The dropped bare "tributi" substring no longer cross-confirms.
    result, letti = _retrieve_aglie(ServiceKey.TRIBUTI_TARI)
    assert result.status is DataStatus.FULFILLED
    (ref,) = result.service_references
    assert ref.service_id == (
        f"{_ISTAT_AGLIE}:comweb:"
        "pagamento-tassa-rifiuti-tari-659-22883-1-809d1b6227988c467e9a06be0ea34eab"
    )
    assert ref.title == "Pagamento Tassa Rifiuti (TARI)"
    assert letti[:2] == [_INDEX_AGLIE, _CAT_TRIBUTI_AGLIE]
    assert len(letti) == 3 and letti[2] == str(ref.source_url)


def test_aglie_every_key_reads_index_plus_its_one_mapped_category():
    # Form of the requests, for every key: the index, then exactly the mapped
    # category — plus at most the single scheda page when one card confirms.
    for key in ServiceKey:
        _, letti = _retrieve_aglie(key)
        atteso_cat = f"{_BASE_AGLIE}/it-it/servizi/{COMWEB_SERVICE_CATEGORY[key]}"
        assert letti[:2] == [_INDEX_AGLIE, atteso_cat], key
        assert len(letti) <= 3, key
