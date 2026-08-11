"""Test di `wordpress_agid.py` (D-09, connettore WordPress-AgID): niente
rete — `mappa_connettore` monkeypatchata, `_Sonda.json`/`.risposta` doppiati
via un finto, stesso stampo di `test_openweb.py`/`test_peopleweb.py`.

Questo connettore è un ADAPTER su `mappa_connettore`: nessuna guardia HTTP
propria da testare (niente `httpx.Client` diretto) — la superficie da
coprire è la traduzione mappa → contratto D-09 e il degrado onesto quando
la mappa manca o non espone nulla.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import treasureiq.wordpress_agid as wp_agid_mod
from treasureiq.mappa_connettore import AssetRest, AssetServizi, CategoriaServizio, MappaConnettore
from treasureiq.sonda_live import ComuneNoto

ISTAT = "999999"
HOST = "comune.esempio.it"
_BASE = "https://www.comune.esempio.it"


def _comune(*, sito: str | None = "www.comune.esempio.it") -> ComuneNoto:
    return ComuneNoto(codice_istat=ISTAT, nome="Esempio", provincia="XX", regione="Regione", sito=sito)


def _mappa(
    *,
    uffici_esposto: bool = True,
    uffici_rest_base: str | None = "amministrazione",
    servizi_esposto: bool = False,
    trasparenza_via: str = "scrape",
    sito: str | None = "www.comune.esempio.it",
) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=ISTAT,
        nome="Esempio",
        sito=sito,
        sondato_il=datetime.now(timezone.utc).isoformat(),
        servizi=AssetServizi(
            esposto=servizi_esposto,
            totale=4 if servizi_esposto else 0,
            categorie=[CategoriaServizio(nome="Anagrafe", conteggio=4, id=7, slug="anagrafe")]
            if servizi_esposto
            else [],
        ),
        uffici=AssetRest(esposto=uffici_esposto, rest_base=uffici_rest_base, totale=3 if uffici_esposto else 0),
        amministrazione_trasparente_via=trasparenza_via,
    )


class _SondaFinta:
    """Doppio minimale: solo gli attributi/metodi che `leggi_wordpress_agid`
    tocca — `.json()`/`.risposta()` restituiscono i doppi preparati dal test,
    `.richieste`/`.raggiungibile` restano quelli di `_Sonda` reale ma non
    contano qui (l'adapter non fa la sua guardia HTTP, la fa `mappa_connettore`
    a monte)."""

    def __init__(self, *, righe_uffici: object = None, status_at: int = 404, guasto_json: bool = False) -> None:
        self.richieste = 0
        self.raggiungibile: bool | None = None
        self._righe_uffici = righe_uffici if righe_uffici is not None else []
        self._status_at = status_at
        self._guasto_json = guasto_json

    def json(self, url: str) -> object:
        if self._guasto_json:
            raise RuntimeError("rete giu'")
        return self._righe_uffici

    def risposta(self, url: str):
        class _Risposta:
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

        return _Risposta(self._status_at)


_RIGHE_UFFICI = [
    {"title": {"rendered": "Anagrafe &amp; Stato Civile"}, "link": f"{_BASE}/amministrazione/anagrafe/"},
    {"title": {"rendered": "Tributi"}, "link": f"{_BASE}/amministrazione/tributi/"},
]


# --- Uffici: mapping indice REST -----------------------------------------


def test_leggi_uffici_wordpress_agid_mapping_base() -> None:
    sonda = _SondaFinta(righe_uffici=_RIGHE_UFFICI)
    uffici = wp_agid_mod._leggi_uffici_wordpress_agid(sonda, _BASE, "amministrazione")

    assert len(uffici) == 2
    primo = uffici[0]
    assert primo.nome == "Anagrafe & Stato Civile"
    assert primo.url == f"{_BASE}/amministrazione/anagrafe/"
    assert primo.source_typed is False
    assert primo.telefoni == []
    assert primo.email == []
    assert primo.pec == []
    assert primo.letto_il


def test_leggi_uffici_wordpress_agid_dedup_url_ripetuti() -> None:
    righe = [
        {"title": {"rendered": "Anagrafe"}, "link": f"{_BASE}/amministrazione/anagrafe/"},
        {"title": {"rendered": "Anagrafe"}, "link": f"{_BASE}/amministrazione/anagrafe/"},
    ]
    sonda = _SondaFinta(righe_uffici=righe)
    uffici = wp_agid_mod._leggi_uffici_wordpress_agid(sonda, _BASE, "amministrazione")
    assert len(uffici) == 1


def test_leggi_uffici_wordpress_agid_cap_200() -> None:
    righe = [
        {"title": {"rendered": f"Ufficio {i}"}, "link": f"{_BASE}/amministrazione/ufficio-{i}/"}
        for i in range(250)
    ]
    sonda = _SondaFinta(righe_uffici=righe)
    uffici = wp_agid_mod._leggi_uffici_wordpress_agid(sonda, _BASE, "amministrazione")
    assert len(uffici) == wp_agid_mod.MAX_UFFICI_INDICE


def test_leggi_uffici_wordpress_agid_json_guasto_ritorna_vuoto() -> None:
    sonda = _SondaFinta(guasto_json=True)
    uffici = wp_agid_mod._leggi_uffici_wordpress_agid(sonda, _BASE, "amministrazione")
    assert uffici == []


def test_leggi_uffici_wordpress_agid_risposta_non_lista_ritorna_vuoto() -> None:
    sonda = _SondaFinta(righe_uffici={"non": "una lista"})
    uffici = wp_agid_mod._leggi_uffici_wordpress_agid(sonda, _BASE, "amministrazione")
    assert uffici == []


def test_leggi_uffici_wordpress_agid_riga_senza_titolo_o_link_scartata() -> None:
    righe = [{"title": {"rendered": ""}, "link": f"{_BASE}/x/"}, {"title": {"rendered": "Solo titolo"}}]
    sonda = _SondaFinta(righe_uffici=righe)
    uffici = wp_agid_mod._leggi_uffici_wordpress_agid(sonda, _BASE, "amministrazione")
    assert uffici == []


# --- Amministrazione Trasparente: confermata o niente --------------------


def test_leggi_at_wordpress_agid_confermata_da_probe_200() -> None:
    sonda = _SondaFinta(status_at=200)
    mappa = _mappa(trasparenza_via="scrape")
    at = wp_agid_mod._leggi_at_wordpress_agid(sonda, _BASE, mappa)
    assert at is not None
    assert at.indice_url == f"{_BASE}/amministrazione-trasparente/"
    assert at.bandi_attivi == []
    assert at.pdf_presenti is False


def test_leggi_at_wordpress_agid_confermata_da_mappa_rest() -> None:
    sonda = _SondaFinta(status_at=404)
    mappa = _mappa(trasparenza_via="REST")
    at = wp_agid_mod._leggi_at_wordpress_agid(sonda, _BASE, mappa)
    assert at is not None
    assert at.indice_url == f"{_BASE}/amministrazione-trasparente/"


def test_leggi_at_wordpress_agid_nessuna_conferma_ritorna_none() -> None:
    sonda = _SondaFinta(status_at=404)
    mappa = _mappa(trasparenza_via="scrape")
    at = wp_agid_mod._leggi_at_wordpress_agid(sonda, _BASE, mappa)
    assert at is None


# --- leggi_wordpress_agid: scheletro end-to-end ---------------------------


def test_leggi_wordpress_agid_mappa_assente_esito_vuoto_onesto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wp_agid_mod, "mappa_connettore", lambda codice_istat: None)
    esito = wp_agid_mod.leggi_wordpress_agid(_comune(), _SondaFinta())
    assert esito.piattaforma == wp_agid_mod.PIATTAFORMA_WORDPRESS_AGID
    assert esito.uffici == []
    assert esito.aree_amministrative == []
    assert esito.amministrazione_trasparente is None


def test_leggi_wordpress_agid_mappa_connettore_lancia_esito_vuoto_onesto(monkeypatch: pytest.MonkeyPatch) -> None:
    def _guasto(codice_istat: str) -> None:
        raise RuntimeError("mappa muta")

    monkeypatch.setattr(wp_agid_mod, "mappa_connettore", _guasto)
    esito = wp_agid_mod.leggi_wordpress_agid(_comune(), _SondaFinta())
    assert esito.piattaforma == wp_agid_mod.PIATTAFORMA_WORDPRESS_AGID
    assert esito.uffici == []


def test_leggi_wordpress_agid_comune_senza_sito_esito_vuoto_onesto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wp_agid_mod, "mappa_connettore", lambda codice_istat: _mappa(sito=None))
    esito = wp_agid_mod.leggi_wordpress_agid(_comune(), _SondaFinta())
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None


def test_leggi_wordpress_agid_uffici_non_esposti_resta_vuoto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wp_agid_mod, "mappa_connettore", lambda codice_istat: _mappa(uffici_esposto=False, uffici_rest_base=None)
    )
    esito = wp_agid_mod.leggi_wordpress_agid(_comune(), _SondaFinta(righe_uffici=_RIGHE_UFFICI))
    assert esito.uffici == []


def test_leggi_wordpress_agid_end_to_end_uffici_e_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wp_agid_mod, "mappa_connettore", lambda codice_istat: _mappa(trasparenza_via="REST"))
    sonda = _SondaFinta(righe_uffici=_RIGHE_UFFICI, status_at=404)

    esito = wp_agid_mod.leggi_wordpress_agid(_comune(), sonda)

    assert esito.piattaforma == wp_agid_mod.PIATTAFORMA_WORDPRESS_AGID
    assert len(esito.uffici) == 2
    assert all(u.source_typed is False for u in esito.uffici)
    assert esito.aree_amministrative == []
    assert esito.amministrazione_trasparente is not None
    assert esito.amministrazione_trasparente.indice_url == f"{_BASE}/amministrazione-trasparente/"


def test_leggi_wordpress_agid_aree_amministrative_sempre_vuoto_anche_con_categorie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CategoriaServizio` non porta un `url`: anche con categorie popolate
    (`servizi_esposto=True`) `aree_amministrative` resta `[]` — onesto, non
    fabbricato (vedi docstring del modulo)."""
    monkeypatch.setattr(
        wp_agid_mod, "mappa_connettore", lambda codice_istat: _mappa(servizi_esposto=True, uffici_esposto=False, uffici_rest_base=None)
    )
    esito = wp_agid_mod.leggi_wordpress_agid(_comune(), _SondaFinta())
    assert esito.aree_amministrative == []


# --- Logo: estrattore puro (nessun fetch) ---------------------------------


def test_estrai_logo_wordpress_agid_svg_inline_header() -> None:
    pagina = '<header><svg><image xlink:href="/assets/stemma.png"/></svg></header>'
    logo = wp_agid_mod.estrai_logo_wordpress_agid(pagina, _BASE, HOST)
    assert logo == f"{_BASE}/assets/stemma.png"


def test_estrai_logo_wordpress_agid_img_brand_wrapper_fallback() -> None:
    pagina = '<div class="it-brand-wrapper"><a href="/"><img src="/img/logo.png" alt="logo"></a></div>'
    logo = wp_agid_mod.estrai_logo_wordpress_agid(pagina, _BASE, HOST)
    assert logo == f"{_BASE}/img/logo.png"


def test_estrai_logo_wordpress_agid_rifiuta_src_fuori_host() -> None:
    pagina = '<header><svg><image xlink:href="https://evil.example.com/logo.png"/></svg></header>'
    assert wp_agid_mod.estrai_logo_wordpress_agid(pagina, _BASE, HOST) is None


def test_estrai_logo_wordpress_agid_nessun_markup_ritorna_none() -> None:
    assert wp_agid_mod.estrai_logo_wordpress_agid("<html><body>nulla qui</body></html>", _BASE, HOST) is None


def test_estrai_logo_wordpress_agid_pagina_vuota_ritorna_none() -> None:
    assert wp_agid_mod.estrai_logo_wordpress_agid("", _BASE, HOST) is None
