"""Test di `openweb.py` (D-09, connettore SoluzioniPA OpenWeb): niente rete
— guardie isolate via monkeypatch, stesso stampo di `test_egov.py`
(`_StreamFinto`/`_ClientFinto`).

Fixture reali Collegno (TO, `api/tests/fixtures/openweb_*.html`, CK-3: markup
non verificabile a tavolino): `amministrazione/uffici/` (10 uffici in pagina
1, paginazione a finestra scorrevole `1 2 3 ... 6 7`) e la home (logo inline
SVG dentro `<header>`, AT su sottodominio vendor perché la pagina
same-domain risponde 404 — osservato reale).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import treasureiq.openweb as openweb_mod
from treasureiq.sonda_live import ComuneNoto

ISTAT = "001090"
HOST = "comune.collegno.to.it"
_BASE_COLLEGNO = "https://www.comune.collegno.to.it"

_FIXTURES = Path(__file__).parent / "fixtures"


def _leggi_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text("utf-8")


def _comune(*, sito: str | None = "www.comune.collegno.to.it") -> ComuneNoto:
    return ComuneNoto(codice_istat=ISTAT, nome="Collegno", provincia="TO", regione="Piemonte", sito=sito)


class _SondaFinta:
    """Doppio minimale: solo i due attributi che `leggi_openweb` aggiorna."""

    def __init__(self) -> None:
        self.richieste = 0
        self.raggiungibile: bool | None = None


# --- Guardia security (W1): schema, host post-redirect, size-cap -------


class _StreamFinto:
    """Doppio di `httpx.Client().stream(...)` come context manager, stesso
    stampo di `test_egov.py`."""

    def __init__(self, status_code: int, url: str, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.status_code = status_code
        self.url = url
        self.headers = headers
        self._chunks = chunks

    def __enter__(self) -> "_StreamFinto":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def iter_bytes(self):
        yield from self._chunks


class _ClientFinto:
    def __init__(self, stream_resp: _StreamFinto, **_kwargs: object) -> None:
        self._stream_resp = stream_resp

    def __enter__(self) -> "_ClientFinto":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def stream(self, _method: str, _url: str) -> _StreamFinto:
        return self._stream_resp


def test_guardia_schema_non_http_rifiutato() -> None:
    assert openweb_mod._richiedi_con_guardia("file:///etc/passwd", HOST, timeout=8.0) is None


def test_guardia_redirect_fuori_host_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(200, "https://evil.example.com/", {}, [b"<html></html>"])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert openweb_mod._richiedi_con_guardia(_BASE_COLLEGNO, HOST, timeout=8.0) is None


def test_guardia_size_cap_streaming_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk = b"x" * (openweb_mod.MAX_RISPOSTA_BYTES + 1000)
    stream = _StreamFinto(200, _BASE_COLLEGNO, {}, [chunk, chunk])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert openweb_mod._richiedi_con_guardia(_BASE_COLLEGNO, HOST, timeout=8.0) is None


def test_guardia_stato_non_200_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, _BASE_COLLEGNO, {}, [])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert openweb_mod._richiedi_con_guardia(_BASE_COLLEGNO, HOST, timeout=8.0) is None


# --- Uffici: fixture reale Collegno (index-only, source_typed=False) ----


def test_leggi_uffici_openweb_fixture_reale_collegno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Indice reale di Collegno: >0 uffici, permalink
    `/amministrazione/unita_organizzativa/{slug}/`, MAI recapiti (deferred,
    on-demand) — `source_typed=False` per ogni voce. Il doppio risponde con
    la STESSA pagina 1 a qualunque URL: la paginazione si ferma perché i
    link `/page/N/` letti in pagina 1 vengono esauriti (nessuna pagina
    nuova scoperta oltre il massimo visto)."""
    pagina_uffici = _leggi_fixture("openweb_uffici_collegno.html")
    stream = _StreamFinto(200, _BASE_COLLEGNO + "/amministrazione/uffici/", {}, [pagina_uffici.encode("utf-8")])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    sonda = _SondaFinta()
    uffici = openweb_mod._leggi_uffici_openweb(_BASE_COLLEGNO, HOST, sonda, 8.0)

    assert len(uffici) > 0
    primo = uffici[0]
    assert primo.nome != ""
    assert re.search(r"/amministrazione/unita_organizzativa/[^/]+/?$", primo.url)
    assert primo.source_typed is False
    assert primo.telefoni == []
    assert primo.email == []
    assert primo.pec == []
    assert sonda.richieste >= 1


def test_leggi_uffici_openweb_dedup_url_ripetuti(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lo stesso link ripetuto due volte nel markup non produce due
    uffici — dedup per URL, stesso taglio di `egov._leggi_uffici_egov`."""
    pagina = (
        '<a href="/amministrazione/unita_organizzativa/anagrafe/"><h3>Anagrafe</h3></a>'
        '<a href="/amministrazione/unita_organizzativa/anagrafe/"><h3>Anagrafe</h3></a>'
    )
    stream = _StreamFinto(200, _BASE_COLLEGNO + "/amministrazione/uffici/", {}, [pagina.encode("utf-8")])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    uffici = openweb_mod._leggi_uffici_openweb(_BASE_COLLEGNO, HOST, _SondaFinta(), 8.0)
    assert len(uffici) == 1


def test_leggi_uffici_openweb_fetch_falso_ritorna_vuoto(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, _BASE_COLLEGNO + "/amministrazione/uffici/", {}, [])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    uffici = openweb_mod._leggi_uffici_openweb(_BASE_COLLEGNO, HOST, _SondaFinta(), 8.0)
    assert uffici == []


class _ClientPerUrl:
    """Doppio di `httpx.Client` che risponde secondo l'URL richiesto —
    stesso stampo di `test_egov.py._ClientPerUrl`."""

    def __init__(self, mappa: dict[str, str], *, muti: set[str] | None = None, **_kwargs: object) -> None:
        self._mappa = mappa
        #: URL che devono rispondere 404 anche se `_BASE_COLLEGNO` (prefisso
        #: di OGNI URL del comune) matcherebbe altrimenti la home — senza
        #: questo un path più specifico assente dalla mappa "vince" per
        #: caso sulla entry della home invece di 404are come voluto dal test.
        self._muti = muti or set()

    def __enter__(self) -> "_ClientPerUrl":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def stream(self, _method: str, url: str) -> _StreamFinto:
        if url in self._muti:
            return _StreamFinto(404, url, {}, [])
        migliore: tuple[str, str] | None = None
        for prefisso, pagina in self._mappa.items():
            if url.startswith(prefisso) and (migliore is None or len(prefisso) > len(migliore[0])):
                migliore = (prefisso, pagina)
        if migliore is None:
            return _StreamFinto(404, url, {}, [])
        return _StreamFinto(200, url, {}, [migliore[1].encode("utf-8")])


def test_leggi_uffici_openweb_segue_paginazione_finestra_scorrevole(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pager a finestra scorrevole (`1 2 3 ... 6 7`, osservato reale su
    Collegno): la pagina 1 non linka `page/4/` esplicitamente ma linka
    `page/7/` — la pagina 2 deve comunque essere seguita perché sotto il
    massimo visto (7), non fermarsi al primo `N+1` assente dal pager."""
    pagina_1 = (
        '<a href="/amministrazione/unita_organizzativa/ufficio-1/"><h3>Ufficio 1</h3></a>'
        '<a href="/amministrazione/uffici/page/2/">2</a>'
        '<a href="/amministrazione/uffici/page/7/">7</a>'
    )
    pagina_2 = '<a href="/amministrazione/unita_organizzativa/ufficio-2/"><h3>Ufficio 2</h3></a>'
    pagine = {
        _BASE_COLLEGNO + "/amministrazione/uffici/page/2/": pagina_2,
        _BASE_COLLEGNO + "/amministrazione/uffici/": pagina_1,
    }
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientPerUrl(pagine, **kwargs))

    uffici = openweb_mod._leggi_uffici_openweb(_BASE_COLLEGNO, HOST, _SondaFinta(), 8.0)
    urls = {u.url for u in uffici}
    assert any("ufficio-1" in u for u in urls)
    assert any("ufficio-2" in u for u in urls)


# --- Amministrazione Trasparente: same-domain + fallback vendor --------


def test_leggi_at_openweb_same_domain_200(monkeypatch: pytest.MonkeyPatch) -> None:
    at_url = _BASE_COLLEGNO + "/amministrazione/amministrazione-trasparente/"
    stream = _StreamFinto(200, at_url, {}, [b"<html>AT</html>"])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    at = openweb_mod._leggi_at_openweb("<html></html>", _BASE_COLLEGNO, HOST, _SondaFinta(), 8.0)
    assert at is not None
    assert at.indice_url == at_url


def test_leggi_at_openweb_fallback_link_vendor_home_reale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Osservato reale su Collegno: la pagina same-domain risponde 404, la
    AT reale vive su un sottodominio vendor SoluzioniPA/OpenWeb — trovata
    per HREF nella home già letta, MAI fetchata."""
    stream = _StreamFinto(404, _BASE_COLLEGNO + "/amministrazione/amministrazione-trasparente/", {}, [])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    pagina_home = _leggi_fixture("openweb_home_collegno.html")
    at = openweb_mod._leggi_at_openweb(pagina_home, _BASE_COLLEGNO, HOST, _SondaFinta(), 8.0)
    assert at is not None
    assert at.indice_url is not None
    assert "openweb/trasparenza" in at.indice_url or "soluzionipa.it" in at.indice_url


def test_leggi_at_openweb_nessun_link_trovato_ritorna_none(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, _BASE_COLLEGNO + "/amministrazione/amministrazione-trasparente/", {}, [])
    monkeypatch.setattr(openweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    at = openweb_mod._leggi_at_openweb("<html>nulla qui</html>", _BASE_COLLEGNO, HOST, _SondaFinta(), 8.0)
    assert at is None


# --- Logo: estrattore puro (nessun fetch) -------------------------------


def test_estrai_logo_openweb_fixture_reale_collegno() -> None:
    """Il logo reale di Collegno vive su `static-www.comune.collegno.to.it`
    — un CDN SOTTO il dominio del comune, non l'host esatto: l'estrattore
    deve accettarlo (`_stesso_sito`, non `_stesso_host` stretto)."""
    pagina_home = _leggi_fixture("openweb_home_collegno.html")
    logo = openweb_mod.estrai_logo_openweb(pagina_home, _BASE_COLLEGNO, HOST)
    assert logo is not None
    assert logo.startswith("https://")
    assert "comune.collegno.to.it" in logo


def test_estrai_logo_openweb_rifiuta_src_fuori_dominio() -> None:
    pagina = '<header><svg><image xlink:href="https://evil.example.com/logo.png"/></svg></header>'
    assert openweb_mod.estrai_logo_openweb(pagina, _BASE_COLLEGNO, HOST) is None


def test_estrai_logo_openweb_accetta_src_relativo_same_host() -> None:
    pagina = '<header><svg><image xlink:href="/assets/stemma.png"/></svg></header>'
    logo = openweb_mod.estrai_logo_openweb(pagina, _BASE_COLLEGNO, HOST)
    assert logo == _BASE_COLLEGNO + "/assets/stemma.png"


def test_estrai_logo_openweb_senza_header_ritorna_none() -> None:
    assert openweb_mod.estrai_logo_openweb("<html><body>nulla qui</body></html>", _BASE_COLLEGNO, HOST) is None


def test_estrai_logo_openweb_pagina_vuota_ritorna_none() -> None:
    assert openweb_mod.estrai_logo_openweb("", _BASE_COLLEGNO, HOST) is None


# --- leggi_openweb: scheletro end-to-end --------------------------------


def test_leggi_openweb_comune_senza_sito_esito_vuoto_onesto() -> None:
    esito = openweb_mod.leggi_openweb(_comune(sito=None), _SondaFinta())
    assert esito.piattaforma == openweb_mod.PIATTAFORMA_OPENWEB
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None
    assert esito.aree_amministrative == []


def test_leggi_openweb_rete_muta_esito_vuoto_onesto_mai_eccezione(monkeypatch: pytest.MonkeyPatch) -> None:
    def _guasto(**_kwargs: object):
        raise RuntimeError("rete giu'")

    monkeypatch.setattr(openweb_mod.httpx, "Client", _guasto)

    esito = openweb_mod.leggi_openweb(_comune(), _SondaFinta())
    assert esito.piattaforma == openweb_mod.PIATTAFORMA_OPENWEB
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None
    assert esito.aree_amministrative == []


def test_leggi_openweb_end_to_end_fixture_reali_collegno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query end-to-end sulle fixture reali Collegno: home → uffici (indice
    reale), AT (fallback vendor dalla home dopo il 404 same-domain) e aree
    (categorie servizi reali, lette dal doppio che ripiega sulla home in
    assenza di un `/servizi/` dedicato) — degrado PER-SEZIONE, non
    tutto-o-niente."""
    pagine = {
        _BASE_COLLEGNO + "/amministrazione/uffici/": _leggi_fixture("openweb_uffici_collegno.html"),
        _BASE_COLLEGNO: _leggi_fixture("openweb_home_collegno.html"),
        # `/amministrazione/amministrazione-trasparente/` NON è nella mappa
        # apposta: _ClientPerUrl ripiega su 404 -> AT ripiega sul link
        # vendor letto dalla home (osservato reale su Collegno).
    }
    muti = {_BASE_COLLEGNO + "/amministrazione/amministrazione-trasparente/"}
    monkeypatch.setattr(
        openweb_mod.httpx, "Client", lambda **kwargs: _ClientPerUrl(pagine, muti=muti, **kwargs)
    )

    sonda = _SondaFinta()
    esito = openweb_mod.leggi_openweb(_comune(), sonda)

    assert esito.piattaforma == openweb_mod.PIATTAFORMA_OPENWEB
    assert len(esito.uffici) > 0
    assert all(u.source_typed is False for u in esito.uffici)
    assert all("/amministrazione/unita_organizzativa/" in u.url for u in esito.uffici)

    at = esito.amministrazione_trasparente
    assert at is not None
    assert at.indice_url is not None
    assert "openweb/trasparenza" in at.indice_url or "soluzionipa.it" in at.indice_url

    # `/servizi/` non è nella mappa -> il doppio ripiega sulla home (unico
    # prefisso ancora compatibile) -> le categorie linkate lì bastano a
    # popolare `aree_amministrative` con dati reali, non un degrado qui.
    assert len(esito.aree_amministrative) > 0
    assert all("/servizi-categoria/" in area.url for area in esito.aree_amministrative)
    assert sonda.raggiungibile is True
    assert sonda.richieste >= 1
