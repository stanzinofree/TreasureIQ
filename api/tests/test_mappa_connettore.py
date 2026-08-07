"""Parsing della mappa connettore, senza rete: sonda finta, risposte fisse."""

from __future__ import annotations

import pytest

from treasureiq.mappa_connettore import (
    _ANCORE_COSA_OTTIENI,
    Bando,
    CategoriaServizio,
    _bando_da_riga,
    _base_con_schema,
    _categorie,
    _host_senza_www,
    _normalizza_link,
    _prima_presente,
    _prima_sezione,
    _rest_base_categorie,
    _rest_base_tassonomia_per_tipo,
    _servizi_link,
    _sezione,
    _term_bandi,
    _titolo_pagina,
    _totale_rest,
)


class _RispostaFinta:
    def __init__(self, status_code: int, headers: dict[str, str]):
        self.status_code = status_code
        self.headers = headers


class _SondaFinta:
    """Rende ciò che le si dice di rendere; solleva dove non ha una voce, come
    farebbe la sonda vera su una rotta assente."""

    def __init__(self, *, json_per_url=None, risposta_per_url=None):
        self._json = json_per_url or {}
        self._risposta = risposta_per_url or {}

    def json(self, url: str):
        if url not in self._json:
            raise RuntimeError(f"rotta assente: {url}")
        return self._json[url]

    def risposta(self, url: str):
        if url not in self._risposta:
            raise RuntimeError(f"rotta assente: {url}")
        return self._risposta[url]


def test_base_con_schema_antepone_https_e_toglie_slash():
    assert _base_con_schema("www.comune.x.it/") == "https://www.comune.x.it"
    assert _base_con_schema("https://comune.y.it") == "https://comune.y.it"


def test_base_con_schema_vuoto_e_none():
    assert _base_con_schema(None) is None
    assert _base_con_schema("   ") is None


def test_prima_presente_prende_il_primo_del_vocabolario():
    disponibili = {"servizio", "servizi"}
    # L'ordine del vocabolario decide, non quello dell'insieme.
    assert _prima_presente(("servizi", "servizio"), disponibili) == "servizi"
    assert _prima_presente(("mancante",), disponibili) is None


def test_totale_rest_legge_header_x_wp_total():
    base = "https://comune.x.it"
    url = f"{base}/wp-json/wp/v2/servizi?per_page=1"
    sonda = _SondaFinta(risposta_per_url={url: _RispostaFinta(200, {"X-WP-Total": "244"})})
    assert _totale_rest(sonda, base, "servizi") == 244


def test_totale_rest_zero_su_risposta_storta_o_header_assente():
    base = "https://comune.x.it"
    url = f"{base}/wp-json/wp/v2/servizi?per_page=1"
    # 500: conteggio ignoto = 0, mai un numero inventato.
    sonda = _SondaFinta(risposta_per_url={url: _RispostaFinta(500, {"X-WP-Total": "9"})})
    assert _totale_rest(sonda, base, "servizi") == 0
    # 200 ma senza header: ancora 0.
    sonda2 = _SondaFinta(risposta_per_url={url: _RispostaFinta(200, {})})
    assert _totale_rest(sonda2, base, "servizi") == 0
    # Rotta del tutto assente (solleva): 0.
    assert _totale_rest(_SondaFinta(), base, "servizi") == 0


def test_categorie_scarta_gli_zero_e_ordina_per_conteggio():
    base = "https://comune.x.it"
    url = f"{base}/wp-json/wp/v2/categorie_servizio?per_page=100&_fields=id,name,count,slug"
    payload = [
        {"id": 3, "slug": "ambiente", "name": "Ambiente", "count": 3},
        {"id": 4, "slug": "agri", "name": "Agricoltura e pesca", "count": 0},  # scartata
        {"id": 5, "slug": "anagrafe", "name": "Anagrafe e stato civile", "count": 88},
        {"id": 6, "slug": "turismo", "name": "Turismo", "count": 0},  # scartata
    ]
    sonda = _SondaFinta(json_per_url={url: payload})
    cat = _categorie(sonda, base, "categorie_servizio")
    assert cat == [
        CategoriaServizio(nome="Anagrafe e stato civile", conteggio=88, id=5, slug="anagrafe"),
        CategoriaServizio(nome="Ambiente", conteggio=3, id=3, slug="ambiente"),
    ]


def test_servizi_link_titolo_rendered_e_link_relativo_normalizzato():
    base = "https://comune.x.it"
    url = f"{base}/wp-json/wp/v2/servizi?categorie_servizio=259&per_page=60&_fields=title,link"
    payload = [
        {"title": {"rendered": "Permesso ZTL"}, "link": "/servizio/ztl/"},  # relativo
        {"title": {"rendered": "Suolo pubblico"}, "link": "https://comune.x.it/servizio/suolo/"},
        {"title": {"rendered": ""}, "link": "/vuoto/"},  # senza titolo: scartato
        # entità HTML nel title.rendered: vanno decodificate (accenti WP).
        {"title": {"rendered": "Imposta di soggiorno dell&#8217;anno"}, "link": "/servizio/soggiorno/"},
    ]
    sonda = _SondaFinta(json_per_url={url: payload})
    servizi = _servizi_link(sonda, base, "servizi", "categorie_servizio", 259, 60)
    assert [(s.titolo, s.url) for s in servizi] == [
        ("Permesso ZTL", "https://comune.x.it/servizio/ztl/"),
        ("Suolo pubblico", "https://comune.x.it/servizio/suolo/"),
        ("Imposta di soggiorno dell’anno", "https://comune.x.it/servizio/soggiorno/"),
    ]


def test_categorie_vuote_su_rotta_assente():
    assert _categorie(_SondaFinta(), "https://comune.x.it", "categorie_servizio") == []


def test_rest_base_categorie_lega_la_tassonomia_al_cpt_servizi():
    base = "https://comune.x.it"
    url = f"{base}/wp-json/wp/v2/taxonomies"
    tass = {
        "post_tag": {"rest_base": "tags", "types": ["post"]},
        # Applicata al CPT servizio e con «categor» nel nome: è quella giusta.
        "categorie_servizio": {"rest_base": "categorie_servizio", "types": ["servizio"]},
    }
    sonda = _SondaFinta(json_per_url={url: tass})
    assert _rest_base_categorie(sonda, base, "servizio") == "categorie_servizio"


def test_rest_base_categorie_none_se_indice_assente():
    assert _rest_base_categorie(_SondaFinta(), "https://comune.x.it", "servizio") is None


_PAGINA_SERVIZIO = """
<html><head>
<meta property="og:title" content="Permesso di occupazione suolo pubblico" />
</head><body>
<nav><a href="#who-needs"><span>A chi &#232; rivolto</span></a>
<a href="#description"><span>Descrizione</span></a></nav>
<section id="who-needs"><h2>A chi &#232; rivolto</h2>
<p>A cittadini e imprese che occupano suolo pubblico.</p></section>
<section id="description"><h2>Descrizione</h2>
<p>L'occupazione di suolo pubblico dell&#8217;area richiede un permesso.</p></section>
<section id="what-you-get"><h2>Cosa si ottiene</h2>
<p>Il permesso di occupare il suolo pubblico per il periodo richiesto.</p></section>
<section id="costs"><h2>Costi</h2><p>16,00 euro di bollo.</p></section>
</body></html>
"""


def test_sezione_estrae_testo_pulito_e_decodifica_entita():
    d = _sezione(_PAGINA_SERVIZIO, "description")
    assert d == "L'occupazione di suolo pubblico dell’area richiede un permesso."
    a = _sezione(_PAGINA_SERVIZIO, "who-needs")
    assert a == "A cittadini e imprese che occupano suolo pubblico."
    g = _sezione(_PAGINA_SERVIZIO, "what-you-get")
    assert g == "Il permesso di occupare il suolo pubblico per il periodo richiesto."


def test_sezione_none_se_ancora_assente():
    assert _sezione(_PAGINA_SERVIZIO, "how-to-do") is None


# Variante di tema: «Cosa si ottiene» marcata `obtain`, non `what-you-get`
# (comune reale: Figline). `_prima_sezione` deve trovarla tra i candidati.
_PAGINA_OBTAIN = """
<section id="description"><h2>Descrizione</h2><p>Il patrocinio del comune.</p></section>
<section id="needed"><h2>Cosa serve</h2><p>Una domanda in bollo.</p></section>
<section id="obtain"><h2>Cosa si ottiene</h2>
<p>Il patrocinio e l'uso dello stemma comunale.</p></section>
<section id="costs"><h2>Quanto costa</h2><p>Gratuito.</p></section>
"""


def test_prima_sezione_trova_obtain_quando_manca_what_you_get():
    # Sul fixture standard vince `what-you-get`.
    assert _prima_sezione(_PAGINA_SERVIZIO, _ANCORE_COSA_OTTIENI) == (
        "Il permesso di occupare il suolo pubblico per il periodo richiesto."
    )
    # Sulla variante `obtain`, senza `what-you-get`, ripiega su `obtain` e
    # taglia correttamente a `costs` (confine noto).
    assert _prima_sezione(_PAGINA_OBTAIN, _ANCORE_COSA_OTTIENI) == (
        "Il patrocinio e l'uso dello stemma comunale."
    )


def test_prima_sezione_none_se_nessun_candidato():
    assert _prima_sezione("<div id='x'>y</div>", _ANCORE_COSA_OTTIENI) is None


def test_sezione_taglia_a_confine_di_parola():
    lunga = '<div id="description">' + "parola " * 100 + "</div>"
    testo = _sezione(lunga, "description", limite=40)
    assert len(testo) <= 41 and testo.endswith("…") and "parol…" not in testo


def test_titolo_pagina_preferisce_og_title():
    assert _titolo_pagina(_PAGINA_SERVIZIO) == "Permesso di occupazione suolo pubblico"


def test_titolo_pagina_ripiega_su_h1():
    assert _titolo_pagina("<h1>Carta d&#8217;identit&#224;</h1>") == "Carta d’identità"


def test_rest_base_tassonomia_per_tipo_lega_al_cpt_amm_trasparente():
    base = "https://comune.x.it"
    url = f"{base}/wp-json/wp/v2/taxonomies"
    sonda = _SondaFinta(
        json_per_url={
            url: {
                "categorie_servizio": {"rest_base": "categorie_servizio", "types": ["servizio"]},
                "tipologie": {"rest_base": "tipologie", "types": ["amm-trasparente"]},
            }
        }
    )
    assert _rest_base_tassonomia_per_tipo(sonda, base, "amm-trasparente") == "tipologie"


def test_rest_base_tassonomia_per_tipo_none_se_indice_assente():
    assert (
        _rest_base_tassonomia_per_tipo(_SondaFinta(), "https://comune.x.it", "amm-trasparente")
        is None
    )


def test_term_bandi_slug_esatto():
    categorie = [
        CategoriaServizio(nome="Altro", conteggio=3, id=10, slug="altro"),
        CategoriaServizio(nome="Criteri e modalità", conteggio=5, id=20, slug="criteri-e-modalita"),
    ]
    assert _term_bandi(categorie).id == 20


def test_term_bandi_tollerante_su_variante_slug():
    categorie = [
        CategoriaServizio(nome="Altro", conteggio=1, id=1, slug="altro"),
        CategoriaServizio(nome="Criteri", conteggio=2, id=30, slug="criteri-e-modalita-2"),
    ]
    assert _term_bandi(categorie).id == 30


def test_term_bandi_none_se_nessun_candidato():
    categorie = [CategoriaServizio(nome="Altro", conteggio=1, id=1, slug="altro")]
    assert _term_bandi(categorie) is None


def test_term_bandi_ignora_falso_positivo_criteri():
    # slug che contiene "criteri" ma NON è il term dei bandi: non deve matchare
    categorie = [
        CategoriaServizio(nome="Criteri accessibilità", conteggio=3, id=7,
                          slug="criteri-accessibilita"),
    ]
    assert _term_bandi(categorie) is None


def test_bando_da_riga_normalizza_link_e_titolo():
    base = "https://comune.x.it"
    riga = {
        "title": {"rendered": "Bando &amp; contributi 2026"},
        "link": "/amm-trasparente/bando-2026/",
        "date": "2026-01-15T10:00:00",
        "excerpt": {"rendered": "<p>Contributi per le famiglie.</p>"},
        "content": {"rendered": "<p>Testo integrale del bando.</p>"},
    }
    bando = _bando_da_riga(base, riga)
    assert bando == Bando(
        titolo="Bando & contributi 2026",
        url="https://comune.x.it/amm-trasparente/bando-2026/",
        data="2026-01-15T10:00:00",
        anteprima="Contributi per le famiglie.",
    )


def test_bando_da_riga_ripiega_su_content_se_excerpt_vuoto():
    base = "https://comune.x.it"
    riga = {
        "title": {"rendered": "Criterio pubblicazione"},
        "link": "https://comune.x.it/pagina",
        "date": "2026-02-01T00:00:00",
        "excerpt": {"rendered": ""},
        "content": {"rendered": "<p>Contenuto integrale usato come anteprima.</p>"},
    }
    bando = _bando_da_riga(base, riga)
    assert bando.anteprima == "Contenuto integrale usato come anteprima."


def test_bando_da_riga_scarta_titolo_vuoto():
    riga = {
        "title": {"rendered": "   "},
        "link": "https://comune.x.it/pagina",
        "date": "2026-02-01T00:00:00",
        "excerpt": {"rendered": ""},
        "content": {"rendered": ""},
    }
    assert _bando_da_riga("https://comune.x.it", riga) is None


def test_bando_da_riga_scarta_riga_non_dict():
    # riga malformata (non dict) dalla REST: nessuna eccezione, ritorna None
    assert _bando_da_riga("https://comune.x.it", "non-un-dict") is None
    assert _bando_da_riga("https://comune.x.it", ["lista"]) is None
    assert _bando_da_riga("https://comune.x.it", None) is None


def test_host_senza_www_pareggia_apex_e_www():
    # La REST del tema AgID torna i permalink sull'apex, l'anagrafe tiene il www:
    # normalizzati devono pareggiare (altrimenti la scheda-foglia sparisce).
    assert _host_senza_www("www.comune.benevento.it") == "comune.benevento.it"
    assert _host_senza_www("comune.benevento.it") == "comune.benevento.it"
    assert _host_senza_www("www.comune.benevento.it") == _host_senza_www(
        "comune.benevento.it"
    )


def test_host_senza_www_non_apre_altri_host():
    # Solo il prefisso www cade: un host che finge il dominio del comune NON
    # deve pareggiare (guardia SSRF).
    assert _host_senza_www("comune.benevento.it.evil.com") != _host_senza_www(
        "comune.benevento.it"
    )
    assert _host_senza_www("servizi.comune.benevento.it") != _host_senza_www(
        "comune.benevento.it"
    )
