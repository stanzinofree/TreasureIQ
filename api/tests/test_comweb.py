"""Test di `comweb.py` (D-09, connettore ePublic ComWeb): niente rete —
guardie isolate via monkeypatch, stesso stampo di `test_openweb.py`
(`_StreamFinto`/`_ClientFinto`).

Fixture reali Alpignano (TO, `api/tests/fixtures/comweb_*_alpignano.html`,
scouting live CK-3: markup non verificabile a tavolino): indice uffici
(`/it-it/amministrazione/uffici`, card `<h3><a>Nome</a></h3>`, nessuna
paginazione), servizi (`/it-it/servizi`, categorie a un segmento di path) e
la home (logo `<img>` in `.it-brand-wrapper`, NON SVG inline).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import treasureiq.comweb as comweb_mod
from treasureiq.sonda_live import ComuneNoto

ISTAT = "001008"
HOST = "comune.alpignano.to.it"
_BASE_ALPIGNANO = "https://www.comune.alpignano.to.it"

_FIXTURES = Path(__file__).parent / "fixtures"


def _leggi_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text("utf-8")


def _comune(*, sito: str | None = "www.comune.alpignano.to.it") -> ComuneNoto:
    return ComuneNoto(codice_istat=ISTAT, nome="Alpignano", provincia="TO", regione="Piemonte", sito=sito)


class _SondaFinta:
    """Doppio minimale: solo i due attributi che `leggi_comweb` aggiorna."""

    def __init__(self) -> None:
        self.richieste = 0
        self.raggiungibile: bool | None = None


# --- Guardia security (W1): schema, host post-redirect, size-cap -------


class _StreamFinto:
    """Doppio di `httpx.Client().stream(...)` come context manager, stesso
    stampo di `test_openweb.py`."""

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
    assert comweb_mod._richiedi_con_guardia("file:///etc/passwd", HOST, timeout=8.0) is None


def test_guardia_redirect_fuori_host_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(200, "https://evil.example.com/", {}, [b"<html></html>"])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert comweb_mod._richiedi_con_guardia(_BASE_ALPIGNANO, HOST, timeout=8.0) is None


def test_guardia_size_cap_streaming_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk = b"x" * (comweb_mod.MAX_RISPOSTA_BYTES + 1000)
    stream = _StreamFinto(200, _BASE_ALPIGNANO, {}, [chunk, chunk])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert comweb_mod._richiedi_con_guardia(_BASE_ALPIGNANO, HOST, timeout=8.0) is None


def test_guardia_stato_non_200_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, _BASE_ALPIGNANO, {}, [])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert comweb_mod._richiedi_con_guardia(_BASE_ALPIGNANO, HOST, timeout=8.0) is None


# --- Uffici: fixture reale Alpignano + probe hit/miss -------------------


class _ClientPerUrl:
    """Doppio di `httpx.Client` che risponde secondo l'URL richiesto —
    stesso stampo di `test_openweb.py._ClientPerUrl`."""

    def __init__(self, mappa: dict[str, str], *, muti: set[str] | None = None, **_kwargs: object) -> None:
        self._mappa = mappa
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


def test_leggi_uffici_comweb_fixture_reale_alpignano_prima_rotta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Indice reale di Alpignano sulla prima rotta AgID convenzionale
    (`/it-it/amministrazione/uffici`): >0 uffici, MAI recapiti (deferred),
    `source_typed=False` per ogni voce."""
    pagina_uffici = _leggi_fixture("comweb_uffici_alpignano.html")
    stream = _StreamFinto(
        200, _BASE_ALPIGNANO + "/it-it/amministrazione/uffici", {}, [pagina_uffici.encode("utf-8")]
    )
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    uffici = comweb_mod._leggi_uffici_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)

    assert len(uffici) > 0
    primo = uffici[0]
    assert primo.nome != ""
    assert "/it-it/amministrazione/uffici/" in primo.url
    assert primo.source_typed is False
    assert primo.telefoni == []
    assert primo.email == []
    assert primo.pec == []


def test_leggi_uffici_comweb_prima_rotta_muta_seconda_risponde(monkeypatch: pytest.MonkeyPatch) -> None:
    """Se `/it-it/amministrazione/uffici` è muta (404), si prova il
    fallback `/amministrazione/uffici` (D-09, entrambe le rotte AgID
    convenzionali sono provate in ordine)."""
    pagina = '<h3><a href="/amministrazione/uffici/anagrafe-1">Anagrafe</a></h3>'
    pagine = {_BASE_ALPIGNANO + "/amministrazione/uffici": pagina}
    muti = {_BASE_ALPIGNANO + "/it-it/amministrazione/uffici"}
    monkeypatch.setattr(
        comweb_mod.httpx, "Client", lambda **kwargs: _ClientPerUrl(pagine, muti=muti, **kwargs)
    )

    uffici = comweb_mod._leggi_uffici_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert len(uffici) == 1
    assert "/amministrazione/uffici/anagrafe-1" in uffici[0].url


def test_leggi_uffici_comweb_entrambe_le_rotte_mute_ritorna_vuoto(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, _BASE_ALPIGNANO, {}, [])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    uffici = comweb_mod._leggi_uffici_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert uffici == []


def test_leggi_uffici_comweb_dedup_url_ripetuti(monkeypatch: pytest.MonkeyPatch) -> None:
    pagina = (
        '<h3><a href="/it-it/amministrazione/uffici/anagrafe-1">Anagrafe</a></h3>'
        '<h3><a href="/it-it/amministrazione/uffici/anagrafe-1">Anagrafe</a></h3>'
    )
    stream = _StreamFinto(
        200, _BASE_ALPIGNANO + "/it-it/amministrazione/uffici", {}, [pagina.encode("utf-8")]
    )
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    uffici = comweb_mod._leggi_uffici_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert len(uffici) == 1


# --- Aree amministrative: fixture reale Alpignano -----------------------


def test_leggi_aree_comweb_fixture_reale_alpignano(monkeypatch: pytest.MonkeyPatch) -> None:
    """Categorie servizi reali (un segmento di path): le schede di
    dettaglio (due o più segmenti) NON entrano in `aree_amministrative`."""
    pagina_servizi = _leggi_fixture("comweb_servizi_alpignano.html")
    stream = _StreamFinto(200, _BASE_ALPIGNANO + "/it-it/servizi", {}, [pagina_servizi.encode("utf-8")])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    aree = comweb_mod._leggi_aree_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)

    assert len(aree) > 0
    for area in aree:
        pezzi = area.url.split("/it-it/servizi/", 1)[1].rstrip("/")
        assert "/" not in pezzi  # un solo segmento di path, mai una scheda-dettaglio


def test_leggi_aree_comweb_fetch_fallito_ritorna_vuoto(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, _BASE_ALPIGNANO + "/it-it/servizi", {}, [])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    aree = comweb_mod._leggi_aree_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert aree == []


# --- Amministrazione Trasparente: probe + feed RSS best-effort ---------


def test_leggi_at_comweb_probe_200_indice_confermato(monkeypatch: pytest.MonkeyPatch) -> None:
    at_url = _BASE_ALPIGNANO + "/it-it/amministrazione-trasparente/"
    stream = _StreamFinto(200, at_url, {}, [b"<html>AT</html>"])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    at = comweb_mod._leggi_at_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert at.indice_url == at_url
    assert at.bandi_attivi == []
    assert at.pdf_presenti is False


def test_leggi_at_comweb_probe_muto_indice_convenzionale_senza_conferma(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probe 404 su AT e sul feed: `indice_url` resta il valore
    convenzionale, MAI `None` — D-10, link noto non verificato."""
    stream = _StreamFinto(404, _BASE_ALPIGNANO, {}, [])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    at = comweb_mod._leggi_at_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert at.indice_url == _BASE_ALPIGNANO + "/it-it/amministrazione-trasparente/"
    assert at.bandi_attivi == []


def test_leggi_bandi_feed_comweb_item_riconosciuti(monkeypatch: pytest.MonkeyPatch) -> None:
    feed = """<?xml version="1.0"?>
    <rss><channel>
      <item><title>Bando gara appalto pulizie</title><link>https://www.comune.alpignano.to.it/it-it/bando-1</link></item>
      <item><title><![CDATA[Avviso pubblico lavori]]></title><link><![CDATA[https://www.comune.alpignano.to.it/it-it/bando-2]]></link></item>
    </channel></rss>"""
    stream = _StreamFinto(
        200, _BASE_ALPIGNANO + "/it-it/feed-rss/bandi-e-avvisi-di-gara", {}, [feed.encode("utf-8")]
    )
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    bandi = comweb_mod._leggi_bandi_feed_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert len(bandi) == 2
    assert bandi[0].titolo == "Bando gara appalto pulizie"
    assert bandi[0].url == "https://www.comune.alpignano.to.it/it-it/bando-1"
    assert bandi[1].titolo == "Avviso pubblico lavori"
    assert bandi[1].pdf_url is None


def test_leggi_bandi_feed_comweb_forma_irriconoscibile_degrada_vuoto(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(200, _BASE_ALPIGNANO + "/it-it/feed-rss/bandi-e-avvisi-di-gara", {}, [b"<html>non un feed</html>"])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    bandi = comweb_mod._leggi_bandi_feed_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert bandi == []


def test_leggi_bandi_feed_comweb_fetch_fallito_ritorna_vuoto(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, _BASE_ALPIGNANO + "/it-it/feed-rss/bandi-e-avvisi-di-gara", {}, [])
    monkeypatch.setattr(comweb_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    bandi = comweb_mod._leggi_bandi_feed_comweb(_BASE_ALPIGNANO, HOST, _SondaFinta(), 8.0)
    assert bandi == []


# --- Logo: estrattore puro (nessun fetch) -------------------------------


def test_estrai_logo_comweb_fixture_reale_alpignano() -> None:
    """Il logo reale di Alpignano vive in `.it-brand-wrapper` come `<img>`
    (fallback, NON SVG inline — mai osservato su questo comune)."""
    pagina_home = _leggi_fixture("comweb_home_alpignano.html")
    logo = comweb_mod.estrai_logo_comweb(pagina_home, _BASE_ALPIGNANO, HOST)
    assert logo is not None
    assert logo.startswith("https://")
    assert "comune.alpignano.to.it" in logo
    assert "/it-it/immagine/" in logo


def test_estrai_logo_comweb_svg_inline_prevale_su_img(monkeypatch: pytest.MonkeyPatch) -> None:
    pagina = (
        '<header><svg><image xlink:href="/assets/stemma.svg"/></svg>'
        '<div class="it-brand-wrapper"><img src="/assets/altro.png"></div></header>'
    )
    logo = comweb_mod.estrai_logo_comweb(pagina, _BASE_ALPIGNANO, HOST)
    assert logo == _BASE_ALPIGNANO + "/assets/stemma.svg"


def test_estrai_logo_comweb_fallback_img_brand_wrapper_senza_svg() -> None:
    pagina = '<header><div class="it-brand-wrapper"><img src="/it-it/immagine/img-1"></div></header>'
    logo = comweb_mod.estrai_logo_comweb(pagina, _BASE_ALPIGNANO, HOST)
    assert logo == _BASE_ALPIGNANO + "/it-it/immagine/img-1"


def test_estrai_logo_comweb_rifiuta_src_fuori_dominio_esatto() -> None:
    """Guardia STRETTA (`_stesso_host`, non tollerante-a-sottodominio): un
    CDN sotto lo stesso dominio verrebbe scartato — a differenza di
    OpenWeb."""
    pagina = '<header><div class="it-brand-wrapper"><img src="https://cdn.comune.alpignano.to.it/logo.png"></div></header>'
    assert comweb_mod.estrai_logo_comweb(pagina, _BASE_ALPIGNANO, HOST) is None


def test_estrai_logo_comweb_svg_fuori_dominio_ripiega_su_img_same_host() -> None:
    pagina = (
        '<header><svg><image xlink:href="https://evil.example.com/logo.svg"/></svg>'
        '<div class="it-brand-wrapper"><img src="/it-it/immagine/img-1"></div></header>'
    )
    logo = comweb_mod.estrai_logo_comweb(pagina, _BASE_ALPIGNANO, HOST)
    assert logo == _BASE_ALPIGNANO + "/it-it/immagine/img-1"


def test_estrai_logo_comweb_senza_header_ritorna_none() -> None:
    assert comweb_mod.estrai_logo_comweb("<html><body>nulla qui</body></html>", _BASE_ALPIGNANO, HOST) is None


def test_estrai_logo_comweb_pagina_vuota_ritorna_none() -> None:
    assert comweb_mod.estrai_logo_comweb("", _BASE_ALPIGNANO, HOST) is None


# --- leggi_comweb: scheletro end-to-end ----------------------------------


def test_leggi_comweb_comune_senza_sito_esito_vuoto_onesto() -> None:
    esito = comweb_mod.leggi_comweb(_comune(sito=None), _SondaFinta())
    assert esito.piattaforma == comweb_mod.PIATTAFORMA_COMWEB
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None
    assert esito.aree_amministrative == []


def test_leggi_comweb_rete_muta_esito_vuoto_onesto_mai_eccezione(monkeypatch: pytest.MonkeyPatch) -> None:
    def _guasto(**_kwargs: object):
        raise RuntimeError("rete giu'")

    monkeypatch.setattr(comweb_mod.httpx, "Client", _guasto)

    esito = comweb_mod.leggi_comweb(_comune(), _SondaFinta())
    assert esito.piattaforma == comweb_mod.PIATTAFORMA_COMWEB
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None
    assert esito.aree_amministrative == []


def test_leggi_comweb_end_to_end_fixture_reali_alpignano(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query end-to-end sulle fixture reali Alpignano: home → uffici
    (indice reale), servizi (categorie reali) e AT (probe 200 diretto,
    feed muto -> `bandi_attivi=[]`) — degrado PER-SEZIONE, non
    tutto-o-niente."""
    pagine = {
        _BASE_ALPIGNANO + "/it-it/amministrazione/uffici": _leggi_fixture("comweb_uffici_alpignano.html"),
        _BASE_ALPIGNANO + "/it-it/servizi": _leggi_fixture("comweb_servizi_alpignano.html"),
        _BASE_ALPIGNANO + "/it-it/amministrazione-trasparente/": "<html>AT</html>",
        _BASE_ALPIGNANO: _leggi_fixture("comweb_home_alpignano.html"),
    }
    muti = {_BASE_ALPIGNANO + "/it-it/feed-rss/bandi-e-avvisi-di-gara"}
    monkeypatch.setattr(
        comweb_mod.httpx, "Client", lambda **kwargs: _ClientPerUrl(pagine, muti=muti, **kwargs)
    )

    sonda = _SondaFinta()
    esito = comweb_mod.leggi_comweb(_comune(), sonda)

    assert esito.piattaforma == comweb_mod.PIATTAFORMA_COMWEB
    assert len(esito.uffici) > 0
    assert all(u.source_typed is False for u in esito.uffici)
    assert all("/it-it/amministrazione/uffici/" in u.url for u in esito.uffici)

    at = esito.amministrazione_trasparente
    assert at is not None
    assert at.indice_url == _BASE_ALPIGNANO + "/it-it/amministrazione-trasparente/"
    assert at.bandi_attivi == []

    assert len(esito.aree_amministrative) > 0
    assert sonda.raggiungibile is True
    assert sonda.richieste >= 1
