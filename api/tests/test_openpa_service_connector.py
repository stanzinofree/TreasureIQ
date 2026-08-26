"""Golden tests for the OpenPA/OpenCity service connector (Ramo 3, Connettore #3).

Net-free: the network is behind the injected ``ServiceFetcher``.  Four layers
are exercised:

- the connector's ``supports``/``retrieve`` contract (single-confirmed →
  ServiceReference; 0/≥2 → NOT_FOUND; identity from the eZ node id, never the
  title; ``service_id`` prefix ``openpa``);
- the pure eZ Find hit parser on REAL search hits captured live from Storo
  (022183, TN) and Lodrino (017090, BS): the citizen URL comes from
  ``extradata.urlAlias`` (not ``link`` = ``read/<id>``), and a ``document``-class
  hit (TARI) is parsed exactly like a ``public_service`` one — proof the query
  must NOT restrict ``classes``;
- the eZ Find ``q`` builder escaping (the shared term ``carta d'identità`` has an
  apostrophe that is a 400 unless escaped);
- the shared recogniser re-run on realistic OpenPA service titles (the CIE title
  arrives with a typographic apostrophe, folded by the recogniser).
"""

from __future__ import annotations

import pytest

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import (
    DataRequest,
    DataStatus,
    FreshnessPolicy,
)
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.openpa_service import (
    OpenPAServiceConnector,
    candidato_da_hit_ezfind,
    costruisci_query_ezfind,
    raccogli_candidati_ezfind,
)
from treasureiq.catalog.service_contracts import (
    SERVICE_SEARCH_TERM,
    ServiceAccessMode,
    ServiceKey,
)
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.mappa_connettore import MappaConnettore

_ISTAT = "022183"  # Storo (TN)
_BASE = "www.comune.storo.tn.it"
_SITE = f"https://{_BASE}"

# ── real search hits, captured live (trimmed to the fields the parser reads) ──

#: Storo, ``carta d'identità`` — a ``public_service`` hit, title with the
#: typographic apostrophe the portal actually serves.
_HIT_CIE = {
    "metadata": {
        "id": 567,
        "classIdentifier": "public_service",
        "name": {"ita-IT": "Appuntamento per rilascio Carta d’Identità Elettronica (CIE)"},
    },
    "extradata": {
        "ita-IT": {
            "urlAlias": "/Servizi/Appuntamento-per-rilascio-Carta-d-Identita-Elettronica-CIE"
        }
    },
    "link": "read/567",  # the API id, deliberately NOT the citizen URL
}

#: Lodrino, ``tari`` — a ``document``-class hit.  It must parse exactly like a
#: ``public_service`` one: TARI is not published under ``public_service``, so the
#: query cannot pin a class.
_HIT_TARI = {
    "metadata": {
        "id": 496,
        "classIdentifier": "document",
        "name": {"ita-IT": "TARI"},
    },
    "extradata": {"ita-IT": {"urlAlias": "/Amministrazione/Documenti-e-dati/Modulistica/TARI"}},
    "link": "read/496",
}


# ── doubles ─────────────────────────────────────────────────────────────────


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
        self.ultimo_base_url: str | None = None

    def scopri_servizi(
        self, *, base_url: str, term: str, limit: int
    ) -> tuple[ServiceCandidate, ...]:
        self.ultimo_base_url = base_url
        self.ultimo_term = term
        return self._candidati

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        return self._pagine.get(url)


def _mappa(*, sito: str = _SITE) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=_ISTAT,
        nome="Storo",
        sito=sito,
        sondato_il="2026-08-23T00:00:00+00:00",
        piattaforma_id="openpa",
    )


def _request(*, source_id: str = _ISTAT, service_key: str | None = "carta_identita") -> DataRequest:
    selection = {"service_key": service_key} if service_key is not None else {}
    return DataRequest(
        request_id="r-1",
        source_id=source_id,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection=selection,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def _connector(fetcher: StubFetcher) -> OpenPAServiceConnector:
    return OpenPAServiceConnector(fetcher)


def _candidato(
    native_id: int, title: str, path: str, *, native_class: str | None = "public_service"
) -> ServiceCandidate:
    # Default ``public_service`` so the existing behavioural tests survive the
    # class-aware filter; the filter cases pass an explicit class.
    return ServiceCandidate(
        native_id=str(native_id),
        title=title,
        url=f"{_SITE}{path}",
        native_class=native_class,
    )


# ── pure eZ Find parser ─────────────────────────────────────────────────────


def test_parser_costruisce_candidato_da_hit_reale_public_service() -> None:
    cand = candidato_da_hit_ezfind(_HIT_CIE, site_base=_SITE)
    assert cand is not None
    assert cand.native_id == "567"  # the eZ node id, not the title
    assert cand.native_class == "public_service"  # eZ class carried onto the candidate
    assert "Carta d’Identità" in cand.title
    # citizen URL from urlAlias, resolved absolute — never ``link`` (read/567)
    assert str(cand.url) == f"{_SITE}/Servizi/Appuntamento-per-rilascio-Carta-d-Identita-Elettronica-CIE"


def test_parser_legge_anche_classe_document() -> None:
    # TARI lives in ``document``, not ``public_service``: it must parse the same.
    cand = candidato_da_hit_ezfind(_HIT_TARI, site_base=_SITE)
    assert cand is not None
    assert cand.native_id == "496"
    assert cand.native_class == "document"  # document is admitted by the allow-list
    assert str(cand.url) == f"{_SITE}/Amministrazione/Documenti-e-dati/Modulistica/TARI"


@pytest.mark.parametrize(
    "hit",
    [
        {"metadata": {"id": 1, "name": {"ita-IT": "x"}}, "extradata": {"ita-IT": {}}},  # no alias
        {"metadata": {"id": 1, "name": {}}, "extradata": {"ita-IT": {"urlAlias": "/x"}}},  # no name
        {"metadata": {"name": {"ita-IT": "x"}}, "extradata": {"ita-IT": {"urlAlias": "/x"}}},  # no id
        {"metadata": "bad", "extradata": "bad"},  # ill-typed
        "not-a-dict",
    ],
)
def test_parser_scarta_hit_malformato(hit: object) -> None:
    assert candidato_da_hit_ezfind(hit, site_base=_SITE) is None


def test_raccogli_legge_searchhits_e_scarta_rumore() -> None:
    payload = {"searchHits": [_HIT_CIE, "junk", _HIT_TARI]}
    cands = raccogli_candidati_ezfind(payload, site_base=_SITE)
    assert tuple(c.native_id for c in cands) == ("567", "496")


@pytest.mark.parametrize("payload", [{}, {"searchHits": None}, [], "x", None])
def test_raccogli_payload_non_valido_e_vuoto(payload: object) -> None:
    assert raccogli_candidati_ezfind(payload, site_base=_SITE) == ()


def test_query_builder_escapa_apostrofo() -> None:
    # The shared term for CIE has an apostrophe; unescaped it is a 400 upstream.
    q = costruisci_query_ezfind("carta d'identità", limit=20)
    assert q == "q = 'carta d\\'identità' and limit 20"


def test_query_builder_nessuna_restrizione_di_classe() -> None:
    # No ``classes [...]``: TARI (document) would be dropped otherwise.
    assert "classes" not in costruisci_query_ezfind("tari", limit=20)


# ── supports contract ───────────────────────────────────────────────────────


def test_supports_solo_openpa_servizi() -> None:
    conn = _connector(StubFetcher())
    req = _request()
    assert conn.supports(req, platform_id="openpa") is True
    assert conn.supports(req, platform_id="comweb") is False


def test_supports_falso_su_superficie_o_capability_errata() -> None:
    conn = _connector(StubFetcher())
    trasp = DataRequest(
        request_id="r-1",
        source_id=_ISTAT,
        surface=Surface.TRANSPARENCY,
        capability=CAPABILITY_SERVICES,
        selection={"service_key": "carta_identita"},
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )
    assert conn.supports(trasp, platform_id="openpa") is False


# ── retrieve resolution ─────────────────────────────────────────────────────


def test_retrieve_singolo_confermato_emette_reference() -> None:
    fetcher = StubFetcher(
        candidati=(
            _candidato(
                567,
                "Appuntamento per rilascio Carta d’Identità Elettronica (CIE)",
                "/Servizi/Appuntamento-per-rilascio-Carta-d-Identita-Elettronica-CIE",
            ),
        )
    )
    conn = _connector(fetcher)
    result = conn.retrieve(_request(), mappa=_mappa(), esito=None)

    assert result.status is DataStatus.FULFILLED
    assert len(result.service_references) == 1
    ref = result.service_references[0]
    assert ref.service_id == f"{_ISTAT}:openpa:567"  # prefix openpa, id not title
    assert ref.provider_platform == "openpa"
    assert ref.options[0].mode is ServiceAccessMode.INFORMATION
    # the connector drove discovery with the shared canonical term + right endpoint
    assert fetcher.ultimo_term == SERVICE_SEARCH_TERM[ServiceKey.CARTA_IDENTITA]
    assert fetcher.ultimo_base_url == f"{_SITE}/opendata/api/content/search/"


def test_retrieve_zero_confermati_not_found() -> None:
    # A candidate whose title the recogniser does not confirm → 0 confirmed.
    fetcher = StubFetcher(candidati=(_candidato(1, "Sagra della polenta", "/Novita/Sagra"),))
    conn = _connector(fetcher)
    result = conn.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND


def test_retrieve_ambiguo_due_confermati_not_found() -> None:
    fetcher = StubFetcher(
        candidati=(
            _candidato(1, "Carta d'identità elettronica", "/Servizi/CIE-1"),
            _candidato(2, "Carta di identità", "/Servizi/CIE-2"),
        )
    )
    conn = _connector(fetcher)
    result = conn.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND


def test_retrieve_host_esterno_scartato() -> None:
    # A payload could carry an off-host url; it must never become source_url.
    fetcher = StubFetcher(
        candidati=(
            ServiceCandidate(
                native_id="9",
                title="Carta d'identità elettronica",
                url="https://evil.example.org/Servizi/CIE",
                native_class="public_service",  # passes the class filter; host guard must still drop it
            ),
        )
    )
    conn = _connector(fetcher)
    result = conn.retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND


def test_retrieve_senza_sito_not_supported() -> None:
    fetcher = StubFetcher()
    conn = _connector(fetcher)
    result = conn.retrieve(_request(), mappa=_mappa(sito=""), esito=None)
    assert result.status is DataStatus.NOT_SUPPORTED


def test_retrieve_chiave_assente_not_found() -> None:
    conn = _connector(StubFetcher())
    result = conn.retrieve(_request(service_key=None), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND


def test_retrieve_source_id_mismatch_alza() -> None:
    conn = _connector(StubFetcher())
    with pytest.raises(ValueError):
        conn.retrieve(_request(source_id="999999"), mappa=_mappa(), esito=None)


# ── recogniser parity on real OpenPA titles ─────────────────────────────────


def test_recogniser_conferma_titolo_cie_reale() -> None:
    # Typographic apostrophe (’) + (CIE): the shared recogniser folds it.
    titolo = "Appuntamento per rilascio Carta d’Identità Elettronica (CIE)"
    assert riconosci_service_key(titolo) is ServiceKey.CARTA_IDENTITA


def test_recogniser_non_confonde_imis_con_imu() -> None:
    # Honest gap (I-1): in TN IMU is titled IMIS; the recogniser does NOT map it
    # to a neighbour — it stays unrecognised, so IMU resolves NOT_FOUND there.
    assert riconosci_service_key("Calcolatore IMIS") is None


# ── filtro class-aware (Fase B → policy allow-list) ──────────────────────────
#
# Policy misurata sul campione dei 28 comuni OpenPA (2026-08-26): un candidato è
# ammesso solo se la sua classe eZ (``classIdentifier``) è in allow-list per la
# key, PRIMA del gate esattamente-1.  Allow-list uniforme sulle 6 chiavi:
# {public_service, document, output}; ``article`` (notizie), ``channel``,
# ``organization`` e le altre classi sono escluse.  Erano la sorgente #1 di
# ambiguità e di confermati-notizia.


def _req(service_key: str) -> DataRequest:
    return _request(service_key=service_key)


def test_allow_list_copre_le_sei_chiavi_e_esclude_le_classi_giuste() -> None:
    # La policy è per-key ma uniforme: tutte e sei le chiavi mappate, stessa lista.
    # Guardia: se una key sparisce dalla mappa, l'override torna 0-candidati per
    # essa (NOT_FOUND onesto), mai un pass-through permissivo.
    from treasureiq.catalog.service_connectors.openpa_service import _CLASSI_AMMESSE

    assert set(_CLASSI_AMMESSE) == set(ServiceKey)
    for ammesse in _CLASSI_AMMESSE.values():
        assert ammesse == frozenset({"public_service", "document", "output"})
        assert not ({"article", "channel", "organization"} & ammesse)


def test_filtro_esclude_articolo_notizia() -> None:
    # Un ``article`` (notizia) il cui titolo il recogniser conferma per la key
    # sarebbe, senza filtro, un confermato SBAGLIATO (pagina di notizia, non un
    # servizio).  L'allow-list lo scarta PRIMA del gate → NOT_FOUND.
    fetcher = StubFetcher(
        candidati=(
            _candidato(
                998,
                "Carta d'identità cartacea: valida fino alla naturale scadenza",
                "/Novita/Notizie/Carta-d-identita-cartacea",
                native_class="article",
            ),
        )
    )
    result = _connector(fetcher).retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND


def test_filtro_risolve_ambiguita_tra_servizio_e_notizia() -> None:
    # Due candidati che il recogniser mappa entrambi a CARTA_IDENTITA: il servizio
    # vero (public_service, id 567) e una notizia (article, id 998).  Senza filtro
    # è 2 → ambiguo → NOT_FOUND.  L'allow-list scarta la notizia → esattamente 1 →
    # FULFILLED, e la reference superstite è il public_service, non la notizia.
    fetcher = StubFetcher(
        candidati=(
            _candidato(
                567,
                "Appuntamento per rilascio Carta d'Identità Elettronica (CIE)",
                "/Servizi/Appuntamento-CIE",
                native_class="public_service",
            ),
            _candidato(
                998,
                "Carta d'identità cartacea: nuove modalità",
                "/Novita/Notizie/Carta-d-identita-cartacea",
                native_class="article",
            ),
        )
    )
    result = _connector(fetcher).retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.FULFILLED
    assert len(result.service_references) == 1
    assert result.service_references[0].service_id == f"{_ISTAT}:openpa:567"


def test_filtro_mantiene_servizio_valido() -> None:
    # Il filtro può solo restringere: un solo ``public_service`` valido risolve
    # comunque (nessun danno al servizio buono).
    fetcher = StubFetcher(
        candidati=(
            _candidato(
                567,
                "Appuntamento per rilascio Carta d'Identità Elettronica (CIE)",
                "/Servizi/Appuntamento-CIE",
                native_class="public_service",
            ),
        )
    )
    result = _connector(fetcher).retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.FULFILLED
    assert result.service_references[0].service_id == f"{_ISTAT}:openpa:567"


def test_filtro_mantiene_document_per_tributi() -> None:
    # TARI/IMU su OpenPA vivono in ``document``/``output``, non ``public_service``:
    # l'allow-list li ammette, così una TARI in classe ``document`` risolve.  (I
    # tributi restano strutturalmente più deboli — il rumore lì non è separabile
    # per classe — ma il filtro non deve uccidere neanche l'unico document vero.)
    fetcher = StubFetcher(
        candidati=(
            _candidato(
                496,
                "TARI",
                "/Amministrazione/Documenti-e-dati/Modulistica/TARI",
                native_class="document",
            ),
        )
    )
    result = _connector(fetcher).retrieve(_req("tributi_tari"), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.FULFILLED
    assert result.service_references[0].service_id == f"{_ISTAT}:openpa:496"


@pytest.mark.parametrize("classe", ["article", "channel", "organization", "image", None])
def test_filtro_zero_candidati_ammessi_not_found(classe: str | None) -> None:
    # Ogni candidato ha un titolo riconosciuto ma una classe esclusa (o assente):
    # l'allow-list svuota il set → 0 → NOT_FOUND onesto, mai una scelta indovinata.
    fetcher = StubFetcher(
        candidati=(
            _candidato(1, "Carta d'identità elettronica", "/x/CIE", native_class=classe),
        )
    )
    result = _connector(fetcher).retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.NOT_FOUND
