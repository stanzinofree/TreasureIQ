"""OpenPA IMIS→TRIBUTI_IMU slice — alias OpenPA-local, gated a una sola key.

In Trentino l'IMU è titolata «IMIS» (Imposta Immobiliare Semplice): il full-text
condiviso ``imu`` non recupera le schede e il recogniser condiviso non le mappa,
così l'IMU trentina cadeva sempre in NOT_FOUND.  Questa slice, tutta locale al
connettore OpenPA:

- allarga la discovery per ``TRIBUTI_IMU`` a ``imu imis`` (eZ Find: spazio = OR);
- accetta i titoli «IMIS/IM.I.S.» come ``TRIBUTI_IMU`` — e SOLO quella key;
- lascia intatti il recogniser condiviso, i contratti e il gate esattamente-1.

Net-free: la rete è dietro uno ``ServiceFetcher`` iniettato.  I candidati sono
schede eZ REALI catturate (read-only) su comuni OpenPA trentini:
Besenello (022013) e Bocenago (022018).
"""

from __future__ import annotations

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import (
    DataRequest,
    DataStatus,
    FreshnessPolicy,
)
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.openpa_service import OpenPAServiceConnector
from treasureiq.catalog.service_contracts import SERVICE_SEARCH_TERM, ServiceKey
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.mappa_connettore import MappaConnettore

# -- harness net-free ------------------------------------------------------

_ISTAT = "022013"
_HOST = "www.comune.besenello.tn.it"
_SITE = f"https://{_HOST}"


class StubFetcher:
    """``ServiceFetcher`` di test: ritorna candidati fissi e registra il termine
    con cui la discovery è stata invocata (per verificare ``imu imis``)."""

    def __init__(self, *, candidati: tuple[ServiceCandidate, ...] = ()) -> None:
        self._candidati = candidati
        self.ultimo_term: str | None = None
        self._pagine: dict[str, str] = {}

    def scopri_servizi(
        self, *, base_url: str, term: str, limit: int
    ) -> tuple[ServiceCandidate, ...]:
        self.ultimo_term = term
        return self._candidati

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        return self._pagine.get(url)


def _mappa(*, sito: str = _SITE, istat: str = _ISTAT) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=istat,
        nome="Comune campione TN",
        sito=sito,
        sondato_il="2026-08-23T00:00:00+00:00",
        piattaforma_id="openpa",
    )


def _request(*, istat: str = _ISTAT, service_key: str = "tributi_imu") -> DataRequest:
    return DataRequest(
        request_id="r-1",
        source_id=istat,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection={"service_key": service_key},
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def _cand(native_id: int, title: str, path: str, native_class: str, *, site: str = _SITE):
    return ServiceCandidate(
        native_id=str(native_id),
        title=title,
        url=f"{site}{path}",
        native_class=native_class,
    )


def _conn(fetcher: StubFetcher) -> OpenPAServiceConnector:
    return OpenPAServiceConnector(fetcher)


# -- fixture reali (catturate su OpenPA trentino, read-only) ---------------

# Besenello 022013 — un solo public_service IMIS: il gate esattamente-1 risolve.
_BESENELLO = (
    _cand(1023, "Calcolatore IMIS", "/Servizi/Calcolatore-IMIS", "public_service"),
    _cand(1021, "Calcolatore IMIS",
          "/Classificazioni/Cosa-puoi-richiedere/Calcolatore-IMIS", "output"),
    _cand(736, "Agevolazione tributaria (IMIS)",
          "/Classificazioni/Cosa-puoi-richiedere/Agevolazione-tributaria-IMIS", "output"),
    _cand(9001, "Regolamento per la disciplina dell'Imposta Immobiliare Semplice (IM.I.S.)",
          "/Amministrazione/Documenti-e-dati/Regolamento-IM.I.S", "document"),
)

# Bocenago 022018 — DUE public_service IMIS distinti: ambiguità onesta (I-1).
_BOC_HOST = "www.comune.bocenago.tn.it"
_BOC_SITE = f"https://{_BOC_HOST}"
_BOCENAGO = (
    _cand(869, "Calcolatore IMIS", "/Servizi/Calcolatore-IMIS", "public_service",
          site=_BOC_SITE),
    _cand(417, "Domanda di agevolazione tributaria (IMIS)",
          "/Servizi/Domanda-di-agevolazione-tributaria-IMIS", "public_service",
          site=_BOC_SITE),
    _cand(414, "Agevolazione tributaria (IMIS)",
          "/Classificazioni/Cosa-puoi-richiedere/Agevolazione-tributaria-IMIS", "output",
          site=_BOC_SITE),
)


# -- retrieval: il termine per TRIBUTI_IMU diventa 'imu imis' --------------


def test_termine_tributi_imu_aggiunge_imis() -> None:
    fetcher = StubFetcher(candidati=_BESENELLO)
    _conn(fetcher).retrieve(_request(), mappa=_mappa(), esito=None)
    # eZ Find tratta lo spazio come OR: recupera sia IMU sia IMIS.
    assert fetcher.ultimo_term == f"{SERVICE_SEARCH_TERM[ServiceKey.TRIBUTI_IMU]} imis"
    assert fetcher.ultimo_term == "imu imis"


def test_termine_altre_key_invariato() -> None:
    conn = _conn(StubFetcher())
    for key in (ServiceKey.TRIBUTI_TARI, ServiceKey.CARTA_IDENTITA,
                ServiceKey.CAMBIO_RESIDENZA):
        assert conn._termine(key) == SERVICE_SEARCH_TERM[key]
        assert "imis" not in conn._termine(key)


# -- conferma: IMIS risolve TRIBUTI_IMU quando è esattamente-1 -------------


def test_imis_public_service_unico_risolve_tributi_imu() -> None:
    fetcher = StubFetcher(candidati=_BESENELLO)
    result = _conn(fetcher).retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.FULFILLED
    assert len(result.service_references) == 1
    ref = result.service_references[0]
    # Fra i ≥2 non-detrito, l'unico public_service IMIS vince (Layer A).
    assert ref.service_id == f"{_ISTAT}:openpa:1023"
    assert ref.title == "Calcolatore IMIS"


def test_imu_titolo_mainland_ancora_risolve() -> None:
    # Regressione: l'alias non deve rompere l'IMU «normale» (recogniser condiviso).
    candidati = (
        _cand(200, "IMU - Imposta Municipale Propria", "/Servizi/IMU", "public_service"),
    )
    result = _conn(StubFetcher(candidati=candidati)).retrieve(
        _request(), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.FULFILLED
    assert result.service_references[0].service_id == f"{_ISTAT}:openpa:200"


# -- gate esattamente-1: ambiguità e detrito → NOT_FOUND onesto -----------


def test_due_public_service_imis_ambiguo_not_found() -> None:
    # Calcolatore IMIS e Domanda di agevolazione (IMIS) sono servizi distinti:
    # nessun nearest-neighbour, la scelta è di un livello superiore (I-1).
    result = _conn(StubFetcher(candidati=_BOCENAGO)).retrieve(
        _request(istat="022018"),
        mappa=_mappa(sito=_BOC_SITE, istat="022018"),
        esito=None,
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


def test_regolamento_imis_solo_e_detrito_not_found() -> None:
    # Un «Regolamento IM.I.S.» solitario è detrito (Layer B, incondizionale):
    # deve dare NOT_FOUND, non passare come servizio.
    candidati = (
        _cand(9001, "Regolamento per la disciplina dell'Imposta Immobiliare Semplice (IM.I.S.)",
              "/Amministrazione/Documenti-e-dati/Regolamento-IM.I.S", "document"),
    )
    result = _conn(StubFetcher(candidati=candidati)).retrieve(
        _request(), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.NOT_FOUND


# -- guardia: l'alias IMIS è gated ESCLUSIVAMENTE a TRIBUTI_IMU -----------


def test_imis_non_riconosciuto_per_altre_key() -> None:
    for key in ("carta_identita", "tributi_tari", "cambio_residenza"):
        result = _conn(StubFetcher(candidati=_BESENELLO)).retrieve(
            _request(service_key=key), mappa=_mappa(), esito=None
        )
        assert result.status is DataStatus.NOT_FOUND, key


def test_riconosce_alias_solo_per_tributi_imu() -> None:
    conn = _conn(StubFetcher())
    assert conn._riconosce("Calcolatore IMIS", ServiceKey.TRIBUTI_IMU) is True
    assert conn._riconosce("Calcolatore IMIS", ServiceKey.TRIBUTI_TARI) is False
    assert conn._riconosce("Calcolatore IMIS", ServiceKey.CARTA_IDENTITA) is False


# -- guardia: la regex IMIS non matcha falsi positivi ---------------------


def test_regex_imis_accetta_forme_reali() -> None:
    conn = _conn(StubFetcher())
    for titolo in ("IMIS", "IM.I.S. 2025", "Calcolatore IMIS",
                   "Modulo richiesta rimborso I.M.I.S", "IMIS-Pertinenze",
                   "Agevolazione tributaria (IMIS)"):
        assert conn._riconosce(titolo, ServiceKey.TRIBUTI_IMU) is True, titolo


def test_regex_imis_rifiuta_falsi() -> None:
    conn = _conn(StubFetcher())
    for titolo in ("in primis le scadenze", "Ufficio optimism", "Servizio IMSI",
                   "Carta d'identità", "Prossimità dei servizi"):
        assert conn._riconosce(titolo, ServiceKey.TRIBUTI_IMU) is False, titolo


# -- il recogniser CONDIVISO resta intatto (l'alias non è leakato) --------


def test_recogniser_condiviso_ignora_imis() -> None:
    # L'alias vive nel connettore OpenPA, non nel recogniser condiviso: qui IMIS
    # resta ignoto (nessun blast-radius su altre famiglie).
    assert riconosci_service_key("Calcolatore IMIS") is None
    assert riconosci_service_key("IM.I.S. 2025") is None
