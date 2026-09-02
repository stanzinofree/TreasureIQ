"""Disambiguazione multi-servizio (DataStatus.DISAMBIGUATION) — gate ≥2 e selezione.

Quando una ServiceKey risolve a ≥2 servizi confermati (es. IMIS/OpenPA-Trentino:
calcolatore, agevolazione, domanda, …) il gate exactly-one non elegge un vincitore
(I-1, nessun nearest-neighbour) ma **non** butta i candidati: emette
``DataStatus.DISAMBIGUATION`` con TUTTE le reference, in forma leggera (solo
INFORMATION, nessun fetch per-candidato).  La scelta la fa il cittadino con un
``service_id`` opaco, risolto da ``seleziona`` con validazione server-side contro
l'insieme confermato corrente: id fuori insieme → rifiuto esplicito, mai il vicino.

Copre (checklist): positivi ≥2 → DISAMBIGUATION con tutte le ref; 1 → FULFILLED e
0 → NOT_FOUND invariati; deduplica (stesso URL canonico collassa e preferisce
public_service; URL distinte — path o query — restano distinte); lookup di selezione
noto → FULFILLED pieno / ignoto o di altro comune → NOT_FOUND; nessun impatto su
TARI/altre key.  Net-free: ``ServiceFetcher`` iniettato, candidati eZ reali (read-only)
di Bocenago 022018 e Besenello 022013.
"""

from __future__ import annotations

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.openpa_service import OpenPAServiceConnector
from treasureiq.catalog.service_contracts import ServiceAccessMode
from treasureiq.mappa_connettore import MappaConnettore

# -- harness net-free -------------------------------------------------------

_ISTAT = "022018"
_HOST = "www.comune.bocenago.tn.it"
_SITE = f"https://{_HOST}"


class TrackingFetcher:
    """``ServiceFetcher`` di test: candidati fissi + pagine stub; registra ogni
    ``leggi_pagina`` per provare che la lista DISAMBIGUATION NON legge pagine."""

    def __init__(
        self,
        *,
        candidati: tuple[ServiceCandidate, ...] = (),
        pagine: dict[str, str] | None = None,
    ) -> None:
        self._candidati = candidati
        self._pagine = pagine or {}
        self.pagine_lette: list[str] = []

    def scopri_servizi(self, *, base_url: str, term: str, limit: int):
        return self._candidati

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        self.pagine_lette.append(url)
        return self._pagine.get(url)


def _mappa(*, sito: str = _SITE, istat: str = _ISTAT) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=istat,
        nome="Bocenago",
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


def _conn(fetcher: TrackingFetcher) -> OpenPAServiceConnector:
    return OpenPAServiceConnector(fetcher)


# -- fixture reali (eZ Find, OpenPA trentino, read-only) --------------------

# Bocenago — DUE public_service IMIS distinti (path diversi): ambiguità onesta.
_BOCENAGO = (
    _cand(869, "Calcolatore IMIS", "/Servizi/Calcolatore-IMIS", "public_service"),
    _cand(417, "Domanda di agevolazione tributaria (IMIS)",
          "/Servizi/Domanda-di-agevolazione-tributaria-IMIS", "public_service"),
    _cand(414, "Agevolazione tributaria (IMIS)",
          "/Classificazioni/Cosa-puoi-richiedere/Agevolazione-tributaria-IMIS", "output"),
)

_ID_CALCOLATORE = f"{_ISTAT}:openpa:869"
_ID_DOMANDA = f"{_ISTAT}:openpa:417"
_ID_AGEV = f"{_ISTAT}:openpa:414"


# -- gate ≥2 → DISAMBIGUATION con tutte le ref ------------------------------


def test_due_confermati_disambiguation_tutte_le_ref() -> None:
    result = _conn(TrackingFetcher(candidati=_BOCENAGO)).retrieve(
        _request(), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.DISAMBIGUATION
    # Con ≥2 public_service il Layer A OpenPA non elegge: tutti i non-detrito
    # confermati diventano scelte (i 2 public_service + la pagina «output» su URL
    # distinto). service_id opachi, nessuna collassata: URL diverse → voci distinte.
    assert {r.service_id for r in result.service_references} == {
        _ID_CALCOLATORE,
        _ID_DOMANDA,
        _ID_AGEV,
    }


def test_disambiguation_reference_leggere_niente_fetch_pagina() -> None:
    # Le ref della lista sono LEGGERE: solo INFORMATION, nessuna pagina letta,
    # anche se le pagine esistono (evita fino a ~N fetch per una lista non scelta).
    fetcher = TrackingFetcher(
        candidati=_BOCENAGO,
        pagine={f"{_SITE}/Servizi/Calcolatore-IMIS": "<html>irrilevante</html>"},
    )
    result = _conn(fetcher).retrieve(_request(), mappa=_mappa(), esito=None)
    assert result.status is DataStatus.DISAMBIGUATION
    assert fetcher.pagine_lette == []
    for ref in result.service_references:
        assert [o.mode for o in ref.options] == [ServiceAccessMode.INFORMATION]


# -- 1 → FULFILLED e 0 → NOT_FOUND invariati --------------------------------


def test_un_confermato_fulfilled_invariato() -> None:
    solo = (_cand(869, "Calcolatore IMIS", "/Servizi/Calcolatore-IMIS", "public_service"),)
    result = _conn(TrackingFetcher(candidati=solo)).retrieve(
        _request(), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.FULFILLED
    assert len(result.service_references) == 1
    assert result.service_references[0].service_id == _ID_CALCOLATORE


def test_zero_confermati_not_found_invariato() -> None:
    # Nessun titolo conferma TRIBUTI_IMU (né alias IMIS) → miss onesto.
    nulla = (_cand(1, "Sagra della polenta", "/Servizi/Sagra", "public_service"),)
    result = _conn(TrackingFetcher(candidati=nulla)).retrieve(
        _request(), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


# -- deduplica --------------------------------------------------------------


def test_dedup_collassa_stesso_url_preferisce_public_service() -> None:
    # Stesso URL canonico, due classi (public_service + output): una risorsa, non
    # due servizi → collassa a 1, tenendo il public_service (il servizio, non la resa).
    conn = _conn(TrackingFetcher())
    ps = _cand(10, "Calcolatore IMIS", "/Servizi/Calcolatore-IMIS", "public_service")
    out = _cand(11, "Calcolatore IMIS", "/Servizi/Calcolatore-IMIS/", "output")
    dedup = conn._dedup_source_url((out, ps))
    assert len(dedup) == 1
    assert dedup[0].native_class == "public_service"


def test_dedup_non_collassa_path_distinti() -> None:
    conn = _conn(TrackingFetcher())
    a = _cand(1, "Calcolatore IMIS", "/Servizi/Calcolatore-IMIS", "public_service")
    b = _cand(2, "Domanda agevolazione IMIS", "/Servizi/Domanda-IMIS", "public_service")
    assert len(conn._dedup_source_url((a, b))) == 2


def test_dedup_non_collassa_query_distinte() -> None:
    # URL guid-style: stesso path, query diversa → servizi DISTINTI (regressione
    # dialetto B). La chiave di dedup normalizza e include la query.
    conn = _conn(TrackingFetcher())
    a = _cand(1, "Servizio A", "/?post_type=servizio&p=1387", "public_service")
    b = _cand(2, "Servizio B", "/?post_type=servizio&p=1400", "public_service")
    assert len(conn._dedup_source_url((a, b))) == 2


# -- selezione: lookup puro dentro l'insieme del turno ----------------------


def test_seleziona_service_id_noto_risolve_pieno() -> None:
    # Scelta valida → FULFILLED della UNA reference, con opzioni PIENE: qui la
    # pagina scelta viene letta (a differenza della lista leggera).
    fetcher = TrackingFetcher(candidati=_BOCENAGO)
    result = _conn(fetcher).seleziona(_request(), mappa=_mappa(), service_id=_ID_DOMANDA)
    assert result.status is DataStatus.FULFILLED
    assert len(result.service_references) == 1
    assert result.service_references[0].service_id == _ID_DOMANDA
    # La selezione legge la pagina scelta (opzioni piene), non le altre.
    assert fetcher.pagine_lette == [f"{_SITE}/Servizi/Domanda-di-agevolazione-tributaria-IMIS"]


def test_seleziona_service_id_ignoto_rifiuta() -> None:
    # service_id non nell'insieme confermato → rifiuto esplicito, mai il vicino.
    result = _conn(TrackingFetcher(candidati=_BOCENAGO)).seleziona(
        _request(), mappa=_mappa(), service_id=f"{_ISTAT}:openpa:999999"
    )
    assert result.status is DataStatus.NOT_FOUND
    assert result.service_references == ()


def test_seleziona_service_id_altro_comune_rifiuta() -> None:
    # Un service_id ben formato ma con ISTAT di un ALTRO comune non appartiene
    # all'insieme di questo turno → rifiuto (nessun cross-comune).
    result = _conn(TrackingFetcher(candidati=_BOCENAGO)).seleziona(
        _request(), mappa=_mappa(), service_id="099999:openpa:869"
    )
    assert result.status is DataStatus.NOT_FOUND


# -- nessun impatto su altre key --------------------------------------------


def test_altra_key_un_confermato_fulfilled() -> None:
    # TARI con un solo servizio → FULFILLED, come sempre (rami 0/1 invariati).
    tari = (_cand(50, "TARI - Tassa sui rifiuti", "/Servizi/TARI", "public_service"),)
    result = _conn(TrackingFetcher(candidati=tari)).retrieve(
        _request(service_key="tributi_tari"), mappa=_mappa(), esito=None
    )
    assert result.status is DataStatus.FULFILLED
    assert result.service_references[0].service_id == f"{_ISTAT}:openpa:50"


def test_altra_key_zero_confermati_not_found() -> None:
    result = _conn(TrackingFetcher(candidati=_BOCENAGO)).retrieve(
        _request(service_key="tributi_tari"), mappa=_mappa(), esito=None
    )
    # I candidati IMIS non confermano TARI → miss onesto (l'alias IMIS è gated a IMU).
    assert result.status is DataStatus.NOT_FOUND
