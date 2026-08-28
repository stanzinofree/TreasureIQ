"""ComWeb tassonomia **life-events** (Ramo 3, Connettore #2 — multi-tassonomia).

~1/4 dei comuni ComWeb (recon 28 ago: 124/503) non usa la tassonomia tematica
(``anagrafe-e-stato-civile``, ``tributi-...``) ma una per **evento-di-vita/attore**
(``essere-cittadino-c``, ``abitare-c``, ``pagare-le-tasse-c``...).  Il connettore
rileva lo schema dall'indice GIÀ scaricato (0 fetch extra) e sceglie gli slug
dalla mappa giusta.

Questi test girano su **fixture reali di Strevi (006168)** — HTML scaricato dal
portale, non sintetico — così le garanzie sono ancorate ai byte veri:

- rilevamento schema life-event sull'indice reale, e **non-regressione** tematica
  su un indice reale (Agliè): un indice tematico non entra MAI nel ramo life-event;
- 5 key con esattamente-una scheda confermata → FULFILLED, ``service_id`` esatto;
- STATO_CIVILE life-event = **multi-slug** (famiglia + cittadino): entrambe le
  categorie visitate, dedup globale per ``native_id``, gate esattamente-uno
  conservato → su Strevi 0 confermate = NOT_FOUND onesto (I-1), non un falso hit;
- indice muto = miss onesto, nessun path fabbricato.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import DataRequest, FreshnessPolicy
from treasureiq.catalog.service_connectors.comweb_service import (
    COMWEB_LIFE_EVENT_CATEGORY,
    ComWebServiceConnector,
    _ComWebDiscovery,
    _rileva_schema,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

_FIXTURES = Path(__file__).parent / "fixtures" / "comweb"

# --- Strevi (006168), tassonomia life-events, host reale ---------------------
_ISTAT = "006168"
_HOST = "www.comune.strevi.al.it"
_BASE = f"https://{_HOST}"
_INDEX = f"{_BASE}/it-it/servizi"


def _fx(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


def _cat(slug: str) -> str:
    return f"{_BASE}/it-it/servizi/{slug}"


#: Pagine reali servite dal transport-fake: indice + le 4 categorie life-event
#: toccate dalle 6 key.  Chi non è qui torna ``None`` (categoria assente/muta).
_PAGINE_STREVI = {
    _INDEX: _fx("strevi_index.html"),
    _cat("essere-cittadino-c"): _fx("strevi_essere-cittadino-c.html"),
    _cat("abitare-c"): _fx("strevi_abitare-c.html"),
    _cat("avere-una-famiglia-c"): _fx("strevi_avere-una-famiglia-c.html"),
    _cat("pagare-le-tasse-c"): _fx("strevi_pagare-le-tasse-c.html"),
}


class _Transport:
    """Transport-fake guardato: registra gli URL letti, serve dal dict."""

    def __init__(self, pagine: dict[str, str]):
        self.pagine = pagine
        self.letti: list[str] = []

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        self.letti.append(url)
        return self.pagine.get(url)


class _Fetcher:
    """Seam ServiceFetcher: espone discovery + lettura pagina (net-free)."""

    def __init__(self, pagine: dict[str, str]):
        self.transport = _Transport(pagine)
        self._discovery = _ComWebDiscovery()

    def scopri_servizi(self, *, base_url: str, term: str, limit: int):
        return self._discovery.scopri_servizi(
            self.transport, base_url=base_url, term=term, limit=limit
        )

    def leggi_pagina(self, *, url: str, official_host: str):
        return self.transport.leggi_pagina(url=url, official_host=official_host)


def _mappa(sito: str | None = _HOST) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=_ISTAT,
        nome="Strevi",
        sito=sito,
        sondato_il="2026-08-28T00:00:00+00:00",
        piattaforma_id="comweb",
        servizi=AssetServizi(esposto=False, rest_base=None, totale=0),
    )


def _request(service_key: ServiceKey) -> DataRequest:
    return DataRequest(
        request_id=f"test:{_ISTAT}",
        source_id=_ISTAT,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection={"service_key": service_key.value},
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def _retrieve(service_key: ServiceKey, pagine: dict[str, str] | None = None):
    fetcher = _Fetcher(_PAGINE_STREVI if pagine is None else pagine)
    connector = ComWebServiceConnector(fetcher)
    result = connector.retrieve(_request(service_key), mappa=_mappa(), esito=None)
    return result, fetcher.transport.letti


def _slug(url: str) -> str:
    return url.rsplit("/", 1)[-1]


# --- rilevamento schema (indice reale, 0 fetch extra) ------------------------


def test_indice_life_event_reale_rilevato():
    # L'indice reale di Strevi espone gli slug per-attore → schema life_event.
    discovery = _ComWebDiscovery()
    slugs = discovery._slug_indice(_fx("strevi_index.html"), _INDEX, _HOST)
    assert "essere-cittadino-c" in slugs and "pagare-le-tasse-c" in slugs
    assert _rileva_schema(slugs) == "life_event"


def test_indice_tematico_reale_non_entra_nel_ramo_life_event():
    # Non-regressione: un indice tematico reale (Agliè) resta THEMATIC — il ramo
    # life-event non lo tocca mai.  Priorità al marcatore noto anche su misto.
    discovery = _ComWebDiscovery()
    ag_host = "www.comune.aglie.to.it"
    ag_index = f"https://{ag_host}/it-it/servizi"
    slugs = discovery._slug_indice(_fx("aglie_index_thematic.html"), ag_index, ag_host)
    assert "anagrafe-e-stato-civile" in slugs
    assert _rileva_schema(slugs) == "thematic"


# --- 5 key → esattamente-una scheda confermata → FULFILLED -------------------

_FULFILLED = {
    ServiceKey.CARTA_IDENTITA: (
        "essere-cittadino-c",
        "006168:comweb:carta-d-identita-elettronica-cie-788-1-1-0052c1075a1722c887344430f8843d33",
    ),
    ServiceKey.CAMBIO_RESIDENZA: (
        "abitare-c",
        "006168:comweb:cambio-residenza-305-15-1-b48e267ff879a9a03db5f99db9893926",
    ),
    ServiceKey.ACCESSO_ATTI: (
        "essere-cittadino-c",
        "006168:comweb:richiedere-l-accesso-agli-atti-317-138-1-3b6732cd9f65b5ea6fe47593ed78d394",
    ),
    ServiceKey.TRIBUTI_IMU: (
        "pagare-le-tasse-c",
        "006168:comweb:pagare-tributi-imu-600-210-1-5f227f78ae688ee2260115d08501a967",
    ),
    ServiceKey.TRIBUTI_TARI: (
        "pagare-le-tasse-c",
        "006168:comweb:pagamento-tassa-rifiuti-tari-659-45-1-a77454aaaf19786987ca0f5eea28ff41",
    ),
}


@pytest.mark.parametrize(
    "service_key,categoria,service_id",
    [(k, c, sid) for k, (c, sid) in _FULFILLED.items()],
    ids=[k.value for k in _FULFILLED],
)
def test_life_event_key_fulfilled(service_key, categoria, service_id):
    # Schema life-event rilevato → si segue lo slug per-attore giusto (non quello
    # tematico) e si conferma l'unica scheda: service_id esatto, mai fabbricato.
    result, letti = _retrieve(service_key)
    assert result.status.name == "FULFILLED"
    ids = [ref.service_id for ref in result.service_references]
    assert ids == [service_id]
    # navigazione bounded: SOLO indice + la categoria mappata (nessun crawl).
    assert [_slug(u) for u in letti[:2]] == ["servizi", categoria]


# --- STATO_CIVILE multi-slug: entrambe visitate, dedup, gate I-1 ------------


def test_stato_civile_multi_slug_not_found_but_visits_both_categories():
    # STATO_CIVILE life-event mappa DUE categorie (famiglia + cittadino).  Su
    # Strevi 0 titoli confermano STATO_CIVILE → NOT_FOUND onesto (gate I-1), ma
    # DEVE aver visitato entrambe le categorie prima di concludere il vuoto.
    assert COMWEB_LIFE_EVENT_CATEGORY[ServiceKey.STATO_CIVILE] == (
        "avere-una-famiglia-c",
        "essere-cittadino-c",
    )
    result, letti = _retrieve(ServiceKey.STATO_CIVILE)
    assert result.status.name == "NOT_FOUND"
    assert result.service_references == ()
    assert [_slug(u) for u in letti] == [
        "servizi",
        "avere-una-famiglia-c",
        "essere-cittadino-c",
    ]


def test_life_event_dedup_globale_su_native_id_tra_categorie():
    # L'unione delle due categorie STATO_CIVILE passa un ``visti`` condiviso: il
    # dedup è GLOBALE per native_id del parser, non per-pagina.  Nessun candidato
    # con native_id duplicato può sopravvivere all'unione.
    fetcher = _Fetcher(_PAGINE_STREVI)
    candidati = fetcher.scopri_servizi(
        base_url=_INDEX, term=ServiceKey.STATO_CIVILE.value, limit=2000
    )
    native_ids = [c.native_id for c in candidati]
    assert len(native_ids) == len(set(native_ids))
    # entrambe le categorie contribuiscono davvero (union non degenere): la
    # scheda CIE vive in ``essere-cittadino-c`` e compare una volta sola.
    cie = "carta-d-identita-elettronica-cie-788-1-1-0052c1075a1722c887344430f8843d33"
    assert native_ids.count(cie) == 1


# --- miss onesti: indice muto, categoria assente ----------------------------


def test_indice_muto_life_event_miss_onesto():
    # Indice non raggiungibile (transport → None): nessun path fabbricato, la
    # discovery torna vuoto e il connettore ripiega su NOT_FOUND.  Un solo fetch.
    result, letti = _retrieve(ServiceKey.CARTA_IDENTITA, pagine={})
    assert result.status.name == "NOT_FOUND"
    assert result.service_references == ()
    assert letti == [_INDEX]
