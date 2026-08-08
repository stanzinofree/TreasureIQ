"""B3: `leggi_at` — indice bandi Amministrazione Trasparente su Municipium.

Senza rete: la sonda è finta, le pagine sono fixture catturate/costruite in
`tests/fixtures/municipium_at/`. La fixture `fiumicino_bando_singolo.html` è
una cattura reale (2026-08-08, `curl -sL -A Mozilla/5.0`); la fixture
`sintetico_aggregatore.html` è sintetica (nessun comune Municipium reale
scoutato espone un vero indice aggregatore — vedi il modulo per lo scout).
"""

from __future__ import annotations

from pathlib import Path

from treasureiq.connettore import AmministrazioneTrasparente
from treasureiq.municipium_at import _e_candidato_bando, leggi_at
from treasureiq.sonda_live import ComuneNoto

FIXTURES = Path(__file__).parent / "fixtures" / "municipium_at"


class _RispostaFinta:
    def __init__(self, status_code: int, text: str, url: str | None = None):
        self.status_code = status_code
        self.text = text
        #: `None` = nessun redirect: la guardia post-fetch in `leggi_at` la
        #: risolve sull'url richiesto (vedi `_SondaFinta.risposta`). Un test
        #: che vuole simulare un redirect passa un `url` diverso.
        self.url = url


class _SondaFinta:
    """Rende ciò che le si dice di rendere; solleva su un url senza voce,
    come farebbe la sonda vera su un host muto."""

    def __init__(self, risposta_per_url: dict[str, _RispostaFinta] | None = None):
        self._risposta = risposta_per_url or {}

    def risposta(self, url: str) -> _RispostaFinta:
        if url not in self._risposta:
            raise RuntimeError(f"rotta assente: {url}")
        risposta = self._risposta[url]
        if risposta.url is None:
            risposta.url = url
        return risposta


def _comune(sito: str = "https://www.comune-test.example.it") -> ComuneNoto:
    return ComuneNoto(
        codice_istat="058091",
        nome="Comune Test",
        provincia="RM",
        regione="Lazio",
        sito=sito,
    )


def test_nessun_candidato_nella_sitemap_ritorna_none():
    """Nessun link nella sitemap somiglia a bandi/gare/avvisi/concorsi:
    degrado onesto, non un `AmministrazioneTrasparente` vuoto (A11)."""
    comune = _comune()
    sonda = _SondaFinta()
    link_sitemap = [
        "https://www.comune-test.example.it/it/news/qualcosa",
        "https://www.comune-test.example.it/it/organizational_unit/anagrafe",
    ]
    assert leggi_at(comune, sonda, link_sitemap) is None


def test_candidato_su_dominio_terzo_e_scartato_dalla_guardia_host():
    """Caso reale Pomezia: la trasparenza vive su un dominio TERZO. La
    guardia host (SSRF, A5) lo scarta anche se il path somiglia a bandi."""
    comune = _comune()
    sonda = _SondaFinta()
    link_sitemap = [
        "https://comune-test.trasparenza-valutazione-merito.it/web/trasparenza/bandi",
    ]
    assert leggi_at(comune, sonda, link_sitemap) is None


def test_bando_rediretto_fuori_host_e_scartato_toctou():
    """SSRF TOCTOU: il candidato è sullo stesso host PRIMA del fetch, ma la
    risposta arriva da un host ESTERNO (redirect seguito dal client). La
    guardia post-fetch deve scartarlo — nessun `AmministrazioneTrasparente`
    costruito da una pagina che non sta davvero sul dominio del comune."""
    comune = _comune()
    url = "https://www.comune-test.example.it/it/public_documents/bando-redirect"
    sonda = _SondaFinta(
        {
            url: _RispostaFinta(
                200,
                "<title>Bando altrove</title>",
                url="https://host-esterno.example.com/it/public_documents/bando-redirect",
            )
        }
    )
    assert leggi_at(comune, sonda, [url]) is None


def test_pagina_bando_singola_reale_fiumicino():
    """Caso reale Fiumicino: ogni bando è la sua stessa pagina, niente
    indice. Estrae titolo verbatim + pdf_url, `indice_url` resta `None`
    perché non è un aggregatore."""
    pagina = (FIXTURES / "fiumicino_bando_singolo.html").read_text("utf-8")
    comune = _comune(sito="https://www.comune.fiumicino.rm.it")
    url = "https://www.comune.fiumicino.rm.it/it/public_documents/bando-agevolazioni-tari-2026"
    sonda = _SondaFinta({url: _RispostaFinta(200, pagina)})

    esito = leggi_at(comune, sonda, [url])

    assert isinstance(esito, AmministrazioneTrasparente)
    assert esito.indice_url is None
    assert len(esito.bandi_attivi) == 1
    bando = esito.bandi_attivi[0]
    assert bando.titolo == "Bando agevolazioni TARI 2026"
    assert bando.url == url
    assert bando.pdf_url == (
        "https://www.comune.fiumicino.rm.it"
        "/s3/2808/allegati/modulistica/imposte/bando-agevolazioni-tari-2026.pdf"
    )
    assert esito.pdf_presenti is True


def test_pagina_aggregatore_sintetica_estrae_voci_interne():
    """Se una pagina candidata contiene a sua volta link-bando (aggregatore),
    quelle voci sostituiscono la lettura a pagina singola e la pagina
    diventa `indice_url`. Un'ancora fuori dominio dentro l'aggregatore resta
    scartata dalla guardia host; una non pertinente non entra nell'elenco.
    Un link interno `.pdf` (allegato della pagina indice, non un bando
    fratello) non conta come voce-aggregatore e non entra tra i bandi."""
    pagina = (FIXTURES / "sintetico_aggregatore.html").read_text("utf-8")
    comune = _comune()
    indice = "https://www.comune-test.example.it/it/amministrazione-trasparente/bandi-e-concorsi"
    sonda = _SondaFinta({indice: _RispostaFinta(200, pagina)})

    esito = leggi_at(comune, sonda, [indice])

    assert isinstance(esito, AmministrazioneTrasparente)
    assert esito.indice_url == indice
    urls = {b.url for b in esito.bandi_attivi}
    assert (
        "https://www.comune-test.example.it/it/public_documents/bando-concorso-pubblico-esami"
        in urls
    )
    assert (
        "https://www.comune-test.example.it/it/public_documents/avviso-pubblico-contributi-affitto-2026"
        in urls
    )
    # esclusa: link .pdf, allegato della pagina indice, non un bando fratello
    assert not any("gara-appalto-servizio-mensa.pdf" in u for u in urls)
    # scartate: non pertinente e fuori dominio
    assert not any("qualcosa-non-attinente" in u for u in urls)
    assert not any("altro-dominio" in u for u in urls)
    assert len(esito.bandi_attivi) == 2
    assert esito.pdf_presenti is False

    titoli = {b.titolo for b in esito.bandi_attivi}
    assert "Bando di concorso pubblico per esami" in titoli
    assert "Avviso pubblico contributi affitto 2026" in titoli


def test_eccezione_di_rete_su_tutti_i_candidati_ritorna_none():
    """Ogni fetch fallisce (host muto): mai un crash, mai un oggetto vuoto."""
    comune = _comune()
    sonda = _SondaFinta()  # nessuna voce: ogni .risposta() solleva
    link_sitemap = ["https://www.comune-test.example.it/it/public_documents/bando-x"]
    assert leggi_at(comune, sonda, link_sitemap) is None


def test_pagina_illeggibile_status_non_200_ritorna_none():
    """Un 404/410 sulla pagina candidata è una pagina assente, non un bando."""
    comune = _comune()
    url = "https://www.comune-test.example.it/it/amministrazione-trasparente/bandi"
    sonda = _SondaFinta({url: _RispostaFinta(410, "")})
    assert leggi_at(comune, sonda, [url]) is None


def test_comune_senza_sito_ritorna_none():
    comune = _comune(sito=None)
    sonda = _SondaFinta()
    assert leggi_at(comune, sonda, ["https://qualcosa/bandi"]) is None


def test_e_candidato_bando_esclude_organizational_unit():
    """Un ufficio (`/it/organizational_unit/sezione-gare`) NON è un bando
    anche se il path contiene "gare": è un ufficio, non una pagina-bando."""
    assert (
        _e_candidato_bando(
            "https://www.comune-test.example.it/it/organizational_unit/sezione-gare"
        )
        is False
    )
    assert (
        _e_candidato_bando(
            "https://www.comune-test.example.it/it/unita_organizzative/"
            "saq-ufficio-contratti-e-gare"
        )
        is False
    )
    # controprova: un vero path bando resta candidato
    assert (
        _e_candidato_bando(
            "https://www.comune-test.example.it/it/public_documents/bando-x"
        )
        is True
    )


def test_link_organizational_unit_escluso_dai_candidati_sitemap():
    """Stesso caso end-to-end via `leggi_at`: un link sitemap verso un
    ufficio non entra mai tra i candidati, mai trattato come pagina-bando."""
    comune = _comune()
    sonda = _SondaFinta()  # nessuna voce: se venisse fetchato, solleverebbe
    link_sitemap = [
        "https://www.comune-test.example.it/it/organizational_unit/sezione-gare",
        "https://www.comune-test.example.it/it/unita_organizzative/"
        "saq-ufficio-contratti-e-gare",
    ]
    assert leggi_at(comune, sonda, link_sitemap) is None


def test_pagina_avviso_con_piu_pdf_resta_un_solo_bando():
    """Riccione: una pagina-avviso con più allegati PDF (`ALLEGATO-A.pdf` …
    `ALLEGATO-F.pdf`) è UN bando con N allegati, non N bandi. I link
    interni `.pdf` non contano come voci-aggregatore (fix ciclo10), quindi
    `interni` resta sotto `MIN_VOCI_AGGREGATORE` e la pagina è letta come
    bando singolo: `pdf_url` prende comunque il primo allegato."""
    pagina = """
    <html><head></head><body>
    <h1>Avviso pubblico selezione operatori</h1>
    <a href="/it/public_documents/avviso-selezione-operatori/ALLEGATO-A.pdf">Allegato A</a>
    <a href="/it/public_documents/avviso-selezione-operatori/ALLEGATO-B.pdf">Allegato B</a>
    <a href="/it/public_documents/avviso-selezione-operatori/ALLEGATO-C.pdf">Allegato C</a>
    </body></html>
    """
    comune = _comune(sito="https://www.comune.riccione.rn.it")
    url = "https://www.comune.riccione.rn.it/it/public_documents/avviso-selezione-operatori"
    sonda = _SondaFinta({url: _RispostaFinta(200, pagina)})

    esito = leggi_at(comune, sonda, [url])

    assert isinstance(esito, AmministrazioneTrasparente)
    assert esito.indice_url is None
    assert len(esito.bandi_attivi) == 1
    bando = esito.bandi_attivi[0]
    assert bando.url == url
    assert bando.titolo == "Avviso pubblico selezione operatori"
    assert bando.pdf_url == (
        "https://www.comune.riccione.rn.it"
        "/it/public_documents/avviso-selezione-operatori/ALLEGATO-A.pdf"
    )
    assert esito.pdf_presenti is True


def test_vero_aggregatore_con_soli_link_html_resta_aggregatore():
    """Un vero indice con ≥2 pagine-bando HTML (non `.pdf`) resta un
    aggregatore, con ≥2 bandi distinti — il fix sui link `.pdf` non deve
    rompere il caso aggregatore reale (Fiumicino-style)."""
    pagina = """
    <html><body>
    <a title="Bando A" href="/it/public_documents/bando-a">Bando A</a>
    <a title="Bando B" href="/it/public_documents/bando-b">Bando B</a>
    <a title="Avviso C" href="/it/public_documents/avviso-c">Avviso C</a>
    </body></html>
    """
    comune = _comune()
    indice = "https://www.comune-test.example.it/it/amministrazione-trasparente/bandi"
    sonda = _SondaFinta({indice: _RispostaFinta(200, pagina)})

    esito = leggi_at(comune, sonda, [indice])

    assert isinstance(esito, AmministrazioneTrasparente)
    assert esito.indice_url == indice
    assert len(esito.bandi_attivi) == 3
    urls = {b.url for b in esito.bandi_attivi}
    assert "https://www.comune-test.example.it/it/public_documents/bando-a" in urls
    assert "https://www.comune-test.example.it/it/public_documents/bando-b" in urls
    assert "https://www.comune-test.example.it/it/public_documents/avviso-c" in urls
