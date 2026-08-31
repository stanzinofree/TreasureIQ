"""Test net-free del lettore servizi CSC OrchardCorePA (comunibootstrapitalia).

Usano fixture reali (slice verbatim degli anchor) catturate da comuni CSC vivi:
Borno (017022, catalogo ricco 3 categorie) e Braone (017027, TARI come TARIP).
Nessuna rete: ``fetch`` è iniettato e mappa URL → fixture on-disk.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

from treasureiq.csc_orchardcore import (
    EsitoCscServizi,
    leggi_csc_servizi,
    risolvi_per_chiave,
    service_key_di,
)

FIXTURES = Path(__file__).parent / "fixtures" / "csc_orchardcore"

BORNO_HOME = "https://www.comune.borno.bs.it"
BRAONE_HOME = "https://www.comune.braone.bs.it"

#: URL relativo (path?query) → file fixture. Categorie senza fixture = muto (None).
BORNO_MAP = {
    "/servizi/": "borno_index.html",
    "/servizi/categoria/anagrafe-e-stato-civile?pagenum=1": "borno_anagrafe_p1.html",
    "/servizi/categoria/anagrafe-e-stato-civile?pagenum=2": "borno_anagrafe_p2.html",
    "/servizi/categoria/anagrafe-e-stato-civile?pagenum=3": "borno_anagrafe_p3.html",
    "/servizi/categoria/tributi-finanze-e-contravvenzioni?pagenum=1": "borno_tributi_p1.html",
    "/servizi/categoria/autorizzazioni?pagenum=1": "borno_autorizzazioni_p1.html",
}
BRAONE_MAP = {
    "/servizi/": "braone_index.html",
    "/servizi/categoria/tributi-finanze-e-contravvenzioni?pagenum=1": "braone_tributi_p1.html",
}


def _chiave_url(url: str) -> str:
    sp = urlsplit(url)
    return sp.path + (f"?{sp.query}" if sp.query else "")


def fetch_da_mappa(mappa: dict[str, str], log: list[str] | None = None):
    """Costruisce un ``fetch`` net-free: URL noto → (None, bytes, url), altrimenti None."""

    def _fetch(url, *, timeout=None, max_bytes=None, host_atteso=None):
        if log is not None:
            log.append(_chiave_url(url))
        nome = mappa.get(_chiave_url(url))
        if nome is None:
            return None
        body = (FIXTURES / nome).read_bytes()
        return (None, body, url)

    return _fetch


def _leggi_borno(log=None) -> EsitoCscServizi:
    return leggi_csc_servizi(
        "017022", home=BORNO_HOME, comune="Borno",
        fetch=fetch_da_mappa(BORNO_MAP, log),
    )


# --------------------------------------------------------------------------- #
# Deep crawl + gate esattamente-uno                                           #
# --------------------------------------------------------------------------- #
def test_borno_deep_crawl_ok():
    esito = _leggi_borno()
    assert esito.esito == "ok"
    assert esito.comune == "Borno"
    # 15 categorie scoperte dall'indice, 3 con fixture (le altre mute → 0).
    assert len(esito.categorie) == 15
    assert esito.per_categoria["anagrafe-e-stato-civile"] == 18
    assert esito.per_categoria["tributi-finanze-e-contravvenzioni"] == 11
    assert esito.per_categoria["autorizzazioni"] > 0
    # tutte e 6 le ServiceKey presenti a catalogo (2 pulite + 4 fan-out).
    assert set(esito.service_keys) == {
        "CARTA_IDENTITA", "CAMBIO_RESIDENZA", "STATO_CIVILE",
        "ACCESSO_ATTI", "TRIBUTI_IMU", "TRIBUTI_TARI",
    }


def test_carta_e_residenza_exactly_one():
    esito = _leggi_borno()
    carta = risolvi_per_chiave(esito, "CARTA_IDENTITA")
    residenza = risolvi_per_chiave(esito, "CAMBIO_RESIDENZA")
    assert carta is not None
    assert carta.url.endswith("/servizio/richiedere-la-carta-d-identita-elettronica-cie")
    assert carta.host == "comune.borno.bs.it"  # service_id dall'URL on-site
    assert residenza is not None
    assert residenza.url.endswith("/servizio/dichiarare-il-cambio-di-residenza")


@pytest.mark.parametrize(
    "chiave", ["STATO_CIVILE", "ACCESSO_ATTI", "TRIBUTI_IMU", "TRIBUTI_TARI"]
)
def test_fanout_ambiguo_not_found(chiave):
    esito = _leggi_borno()
    # ≥2 candidati → gate I-1 blocca (NOT_FOUND onesto).
    candidati = [s for s in esito.servizi if s.service_key == chiave]
    assert len(candidati) >= 2
    assert risolvi_per_chiave(esito, chiave) is None


# --------------------------------------------------------------------------- #
# Paginazione a finestra                                                       #
# --------------------------------------------------------------------------- #
def test_paginazione_anagrafe_segue_tre_pagine():
    log: list[str] = []
    esito = _leggi_borno(log)
    an = "/servizi/categoria/anagrafe-e-stato-civile"
    # p1,p2 aggiungono servizi; p3 (pager a finestra) ripete solo un servizio
    # già visto → 0 nuovi → stop. p4 non viene mai sondata.
    assert f"{an}?pagenum=1" in log
    assert f"{an}?pagenum=2" in log
    assert f"{an}?pagenum=3" in log
    assert f"{an}?pagenum=4" not in log
    # 18 servizi dedup dalle pagine (doppioni titolo/link e cross-pagina collassati).
    anagrafe = [s for s in esito.servizi if s.categoria == "anagrafe-e-stato-civile"]
    assert len(anagrafe) == 18


def test_categoria_muta_si_ferma_subito():
    log: list[str] = []
    _leggi_borno(log)
    # una categoria senza fixture (muta a pagenum=1) non viene ripaginata.
    catasto = "/servizi/categoria/catasto-e-urbanistica"
    assert f"{catasto}?pagenum=1" in log
    assert f"{catasto}?pagenum=2" not in log


# --------------------------------------------------------------------------- #
# Host guard: portale transazionale cross-host escluso                         #
# --------------------------------------------------------------------------- #
def test_host_guard_scarta_servizio_cross_host(tmp_path):
    # pagina categoria con un link on-site e uno al portale transazionale.
    html = (
        "<!doctype html><html><body><main>"
        '<a href="/servizio/dichiarare-il-cambio-di-residenza" '
        'data-element="service-link"><span>Cambio di residenza</span></a>'
        '<a href="https://servizi.comune.borno.bs.it/servizio/pratica-online" '
        'data-element="service-link"><span>Pratica online</span></a>'
        "</main></body></html>"
    )
    idx = (
        "<!doctype html><html><body><main>"
        '<a href="/servizi/categoria/anagrafe-e-stato-civile">Anagrafe</a>'
        "</main></body></html>"
    )
    mappa = {
        "/servizi/": None,  # sovrascritto sotto
    }
    p = tmp_path
    (p / "idx.html").write_text(idx)
    (p / "cat.html").write_text(html)

    def fetch(url, *, timeout=None, max_bytes=None, host_atteso=None):
        k = _chiave_url(url)
        if k == "/servizi/":
            return (None, (p / "idx.html").read_bytes(), url)
        if k == "/servizi/categoria/anagrafe-e-stato-civile?pagenum=1":
            return (None, (p / "cat.html").read_bytes(), url)
        return None

    esito = leggi_csc_servizi("017022", home=BORNO_HOME, comune="Borno", fetch=fetch)
    urls = [s.url for s in esito.servizi]
    assert "https://www.comune.borno.bs.it/servizio/dichiarare-il-cambio-di-residenza" in urls
    assert all("servizi.comune.borno.bs.it" not in u for u in urls)
    assert any("scartati" in n for n in esito.note)


# --------------------------------------------------------------------------- #
# Braone: TARI pubblicata come TARIP (variante lessicale, non assenza)         #
# --------------------------------------------------------------------------- #
def test_braone_tarip_riconosciuta_ma_ambigua():
    esito = leggi_csc_servizi(
        "017027", home=BRAONE_HOME, comune="Braone",
        fetch=fetch_da_mappa(BRAONE_MAP),
    )
    assert esito.esito == "ok"
    # TARI riconosciuta via lessico TARIP → presente, NON assente...
    assert "TRIBUTI_TARI" in esito.service_keys
    tari = [s for s in esito.servizi if s.service_key == "TRIBUTI_TARI"]
    assert any("tarip" in s.url.lower() or "tarip" in s.titolo.lower() for s in tari)
    # ...ma fan-out ≥2 → gate I-1 la tiene NOT_FOUND (onesto).
    assert len(tari) >= 2
    assert risolvi_per_chiave(esito, "TRIBUTI_TARI") is None


def test_service_key_di_non_forza_tari():
    # titolo generico senza lessico rifiuti → nessuna key.
    assert service_key_di("Pagare un verbale al codice della strada") is None
    assert service_key_di("Richiedere la carta d'identità elettronica (CIE)") == "CARTA_IDENTITA"


# --------------------------------------------------------------------------- #
# Casi-vuoto onesti                                                            #
# --------------------------------------------------------------------------- #
def test_indice_muto_irraggiungibile():
    def fetch(url, *, timeout=None, max_bytes=None, host_atteso=None):
        return None  # /servizi/ non risponde

    esito = leggi_csc_servizi("099999", home=BORNO_HOME, comune="X", fetch=fetch)
    assert esito.esito == "irraggiungibile"
    assert esito.servizi == []


def test_home_non_nota_irraggiungibile():
    esito = leggi_csc_servizi("099999", home="", comune="X", fetch=fetch_da_mappa({}))
    assert esito.esito == "irraggiungibile"
    assert "storico.db" in " ".join(esito.note)


def test_indice_senza_categorie_vuoto():
    idx = "<!doctype html><html><body><main><p>nessun servizio</p></main></body></html>"

    def fetch(url, *, timeout=None, max_bytes=None, host_atteso=None):
        if _chiave_url(url) == "/servizi/":
            return (None, idx.encode(), url)
        return None

    esito = leggi_csc_servizi("017022", home=BORNO_HOME, comune="Borno", fetch=fetch)
    assert esito.esito == "vuoto"
    assert esito.categorie == []
    assert any("catalogo assente" in n for n in esito.note)
