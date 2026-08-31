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
    ServizioCsc,
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
    # categoria reale che contiene il falso positivo ERP «edilizia residenziale».
    "/servizi/categoria/salute-benessere-e-assistenza?pagenum=1": "borno_salute_p1.html",
}
BRAONE_MAP = {
    "/servizi/": "braone_index.html",
    "/servizi/categoria/tributi-finanze-e-contravvenzioni?pagenum=1": "braone_tributi_p1.html",
}
#: scenario sintetico del blocker: p3 = SOLO duplicato, ma il pager punta a p4
#: che ha un servizio NUOVO. Il criterio "0-nuovi → stop" perderebbe p4.
PAG_MAP = {
    "/servizi/": "pag_index.html",
    "/servizi/categoria/prova-paginazione?pagenum=1": "pag_p1.html",
    "/servizi/categoria/prova-paginazione?pagenum=2": "pag_p2.html",
    "/servizi/categoria/prova-paginazione?pagenum=3": "pag_p3.html",
    "/servizi/categoria/prova-paginazione?pagenum=4": "pag_p4.html",
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
    # si segue il link "successiva" del pager: p1→p2→p3; p3 non ha link
    # successiva (ultima pagina reale) → stop. p4 non viene mai sondata.
    assert f"{an}?pagenum=1" in log
    assert f"{an}?pagenum=2" in log
    assert f"{an}?pagenum=3" in log
    assert f"{an}?pagenum=4" not in log
    # 18 servizi dedup dalle pagine (doppioni titolo/link e cross-pagina collassati).
    anagrafe = [s for s in esito.servizi if s.categoria == "anagrafe-e-stato-civile"]
    assert len(anagrafe) == 18


def test_paginazione_non_si_ferma_su_pagina_di_soli_duplicati():
    """BLOCKER PR #67: p3 contiene solo un duplicato (0 nuovi) ma il pager punta
    a p4, che ha un servizio nuovo. Il crawler DEVE seguire il pager, non fermarsi
    sui '0 nuovi', altrimenti perde il servizio di p4."""
    log: list[str] = []
    esito = leggi_csc_servizi(
        "099001", home=BORNO_HOME, comune="Prova",
        fetch=fetch_da_mappa(PAG_MAP, log),
    )
    slug = [s.url.rsplit("/", 1)[-1] for s in esito.servizi]
    # tutte e 4 le pagine seguite, incluse p3 (soli dup) e p4 (nuovo).
    cat = "/servizi/categoria/prova-paginazione"
    assert f"{cat}?pagenum=3" in log
    assert f"{cat}?pagenum=4" in log
    # 4 servizi unici: alfa, beta, gamma, delta — delta vive SOLO su p4.
    assert slug == ["servizio-alfa", "servizio-beta", "servizio-gamma", "servizio-delta"]
    assert "servizio-delta" in slug


def test_cap_hard_su_pager_senza_fine():
    """Pager che dichiara sempre 'successiva' → si procede fino a MAX_PAGINE e si
    annota il troncamento (catalogo possibilmente incompleto), senza loop infinito."""
    from treasureiq.csc_orchardcore import MAX_PAGINE

    idx = (
        "<!doctype html><html><body><main>"
        '<a href="/servizi/categoria/infinita">x</a></main></body></html>'
    )
    log: list[str] = []

    def fetch(url, *, timeout=None, max_bytes=None, host_atteso=None):
        k = _chiave_url(url)
        log.append(k)
        if k == "/servizi/":
            return (None, idx.encode(), url)
        # ogni pagina espone un servizio nuovo + link successiva → mai fine.
        import re as _re
        n = int(_re.search(r"pagenum=(\d+)", k).group(1))
        html = (
            "<!doctype html><html><body><main>"
            f'<a href="/servizio/serv-{n}" data-element="service-link"><span>S{n}</span></a>'
            '<nav><ul class="pagination"><li><a aria-label="Vai alla pagina successiva" '
            f'href="/servizi/categoria/infinita?pagenum={n + 1}&amp;Destination=Next">succ</a>'
            "</li></ul></nav></main></body></html>"
        )
        return (None, html.encode(), url)

    esito = leggi_csc_servizi("099002", home=BORNO_HOME, comune="Inf", fetch=fetch)
    fetch_pagine = [k for k in log if "pagenum=" in k]
    assert len(fetch_pagine) == MAX_PAGINE  # fermato dal cap, non oltre
    assert any("limite hard" in n for n in esito.note)


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


# --------------------------------------------------------------------------- #
# Falso positivo ERP: «edilizia residenziale» non è CAMBIO_RESIDENZA          #
# (fix parser CSC, gate I-1 come ultima difesa)                               #
# --------------------------------------------------------------------------- #
ERP_TITOLO = (
    "Richiedere l'assegnazione di un alloggio di edilizia residenziale pubblica (Erp)"
)


def test_service_key_di_erp_non_e_cambio_residenza():
    # il servizio ERP (categoria salute) NON deve matchare CAMBIO_RESIDENZA...
    assert service_key_di(ERP_TITOLO) != "CAMBIO_RESIDENZA"
    # ...mentre il servizio legittimo resta riconosciuto.
    assert service_key_di("Dichiarare il cambio di residenza") == "CAMBIO_RESIDENZA"
    # varianti «residenziale/residenziali» tutte escluse.
    assert service_key_di("Bando edilizia residenziale pubblica") is None
    assert service_key_di("Alloggi residenziali comunali") is None
    # «certificato di residenza» resta un match (non è residenziale).
    assert service_key_di("Certificato di residenza") == "CAMBIO_RESIDENZA"


def test_borno_full_crawl_residenza_esattamente_uno_nonostante_erp():
    """Crawl full con la categoria salute (che contiene l'ERP): la residenza
    deve restare esattamente-1 e risolvere sul cambio, non degradare ad ambigua."""
    esito = _leggi_borno()
    # l'ERP è presente a catalogo (crawl onesto)...
    erp = [s for s in esito.servizi if "residenziale-pubblica-erp" in s.url.lower()]
    assert erp, "il servizio ERP deve essere estratto dalla categoria salute"
    # ...ma NON è etichettato come cambio residenza.
    assert all(s.service_key != "CAMBIO_RESIDENZA" for s in erp)
    # residenza resta esattamente-1 → risolve sul cambio.
    residenza = [s for s in esito.servizi if s.service_key == "CAMBIO_RESIDENZA"]
    assert len(residenza) == 1
    scelto = risolvi_per_chiave(esito, "CAMBIO_RESIDENZA")
    assert scelto is not None
    assert scelto.url.endswith("/servizio/dichiarare-il-cambio-di-residenza")


def test_gate_i1_resta_ultima_difesa_su_residenza():
    """Anche col regex stretto, se il catalogo esponesse 2 servizi residenza
    legittimi il gate I-1 deve restituire None (ambiguo, ultima difesa)."""
    host = "comune.esempio.bs.it"
    due = EsitoCscServizi(
        esito="ok", codice_istat="099000", comune="Esempio",
        home=f"https://www.{host}", servizi=[
            ServizioCsc(
                titolo="Dichiarare il cambio di residenza",
                url=f"https://www.{host}/servizio/cambio-residenza",
                host=host, categoria="anagrafe-e-stato-civile",
                service_key="CAMBIO_RESIDENZA",
            ),
            ServizioCsc(
                titolo="Cambio di residenza per cittadini stranieri",
                url=f"https://www.{host}/servizio/cambio-residenza-stranieri",
                host=host, categoria="anagrafe-e-stato-civile",
                service_key="CAMBIO_RESIDENZA",
            ),
        ],
        categorie=["anagrafe-e-stato-civile"],
        per_categoria={"anagrafe-e-stato-civile": 2},
        service_keys=["CAMBIO_RESIDENZA"], note=[],
    )
    assert risolvi_per_chiave(due, "CAMBIO_RESIDENZA") is None
