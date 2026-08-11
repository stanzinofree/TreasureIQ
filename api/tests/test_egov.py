"""Test di `egov.py` (ciclo 14, brief B4a): niente rete — firma, dispatcher
e guardie isolate via monkeypatch, stesso stampo di `test_registro.py`
(`_StreamFinto`/`_ClientFinto`) e `test_connettore_contratto.py`
(dispatcher).

Fixture "Marino" (D-10, `.kapi/spec.md`): `en=eg176`, due endpoint distinti
osservati (`EGSCHTST.HBL` servizi, `EGSMISTMSIT.HBL` mappa) più un terzo
link "Amministrazione Trasparente" sintetico per verificare il degrado AT.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

import treasureiq.connettore as connettore_mod
import treasureiq.egov as egov_mod
from treasureiq.connettore import AmministrazioneTrasparente, EsitoConnettore, leggi_connettore
from treasureiq.ingest.piattaforma import Piattaforma, firma_da_risposta
from treasureiq.sonda_live import ComuneNoto

ISTAT = "058057"
HOST = "comune.marino.rm.it"

_HOME_MARINO = """
<html><body>
<a href="/EG0/EGSCHTST.HBL?en=eg176&MESSA=PUBBLICA">Servizi on line</a>
<a href="/EG0/EGSMISTMSIT.HBL?en=eg176&FUNZ=1">Mappa del territorio</a>
<a href="/EG0/EGSATTRASP.HBL?en=eg176&FUNZ=2">Amministrazione Trasparente</a>
<a href="/altro/pagina.html">Altro link normale</a>
</body></html>
"""


def _comune(*, sito: str | None = "www.comune.marino.rm.it") -> ComuneNoto:
    return ComuneNoto(codice_istat=ISTAT, nome="Marino", provincia="RM", regione="Lazio", sito=sito)


class _SondaFinta:
    """Doppio minimale: solo i due attributi che `leggi_egov` aggiorna."""

    def __init__(self) -> None:
        self.richieste = 0
        self.raggiungibile: bool | None = None


# --- Firma (D-09 A9) ----------------------------------------------------


def test_firma_egov_riconosciuta_da_endpoint_egs() -> None:
    firma = firma_da_risposta(headers={}, html=_HOME_MARINO)
    assert firma.piattaforma == Piattaforma.EGOV


def test_firma_egov_riconosce_variante_funz() -> None:
    html = '<a href="/EG0/EGSMISTMSIT.HBL?en=eg176&FUNZ=1">mappa</a>'
    firma = firma_da_risposta(headers={}, html=html)
    assert firma.piattaforma == Piattaforma.EGOV


def test_firma_non_egov_per_html_senza_pattern() -> None:
    firma = firma_da_risposta(headers={}, html="<html><body>nulla qui</body></html>")
    assert firma.piattaforma != Piattaforma.EGOV


def test_firma_non_egov_per_url_hbl_senza_en() -> None:
    """Un `.HBL` senza `en=eg###` non è la firma (D-09 A9): niente input
    libero validato a metà."""
    html = '<a href="/EG0/EGSCHTST.HBL?MESSA=PUBBLICA">senza en</a>'
    firma = firma_da_risposta(headers={}, html=html)
    assert firma.piattaforma != Piattaforma.EGOV


# --- Estrazione endpoint (degrado D-10) ---------------------------------


def test_estrai_aree_egov_endpoint_riconosciuti() -> None:
    aree = egov_mod._estrai_aree_egov(_HOME_MARINO, "https://www.comune.marino.rm.it/", HOST)
    urls = {area.url for area in aree}
    assert any("EGSCHTST" in u and "en=eg176" in u for u in urls)
    assert any("EGSMISTMSIT" in u for u in urls)
    assert not any("altro/pagina.html" in u for u in urls)


def test_estrai_aree_egov_scarta_link_fuori_host() -> None:
    html = '<a href="https://evil.example.com/EG0/EGSX.HBL?en=eg1">x</a>'
    aree = egov_mod._estrai_aree_egov(html, "https://www.comune.marino.rm.it/", HOST)
    assert aree == []


def test_estrai_aree_egov_en_malformato_non_estratto() -> None:
    html = '<a href="/EG0/EGSCHTST.HBL?FUNZ=1">senza en</a>'
    aree = egov_mod._estrai_aree_egov(html, "https://www.comune.marino.rm.it/", HOST)
    assert aree == []


# --- Guardia security (W1): schema, host post-redirect, size-cap -------


class _StreamFinto:
    """Doppio di `httpx.Client().stream(...)` come context manager, stesso
    stampo di `test_registro.py`."""

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
    assert egov_mod._richiedi_con_guardia("file:///etc/passwd", HOST, timeout=8.0) is None


def test_guardia_redirect_fuori_host_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guardia post-redirect (`municipium.py:246`): l'host finale, non
    quello richiesto, decide."""
    stream = _StreamFinto(200, "https://evil.example.com/", {}, [b"<html></html>"])
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert egov_mod._richiedi_con_guardia("https://www.comune.marino.rm.it/", HOST, timeout=8.0) is None


def test_guardia_ip_privato_rifiutato_come_host_diverso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nessun elenco di range IP separato (W1): un IP letterale non è mai
    uguale al dominio del comune, quindi la stessa guardia host lo scarta
    con lo stesso confronto usato per qualunque host estraneo."""
    stream = _StreamFinto(200, "http://127.0.0.1/", {}, [b"<html></html>"])
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert egov_mod._richiedi_con_guardia("http://127.0.0.1/", HOST, timeout=8.0) is None


def test_guardia_size_cap_streaming_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Il cap ABORTISCE lo streaming — mai un `len()` post-download (W-3):
    il secondo pezzo non viene mai raggiunto se il primo già sfora."""
    chunk = b"x" * (egov_mod.MAX_RISPOSTA_BYTES + 1000)
    stream = _StreamFinto(200, "https://www.comune.marino.rm.it/", {}, [chunk, chunk])
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert egov_mod._richiedi_con_guardia("https://www.comune.marino.rm.it/", HOST, timeout=8.0) is None


def test_guardia_stato_non_200_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, "https://www.comune.marino.rm.it/", {}, [])
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    assert egov_mod._richiedi_con_guardia("https://www.comune.marino.rm.it/", HOST, timeout=8.0) is None


def test_guardia_ok_stesso_host_sotto_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(
        200, "https://www.comune.marino.rm.it/", {}, [_HOME_MARINO.encode("utf-8")]
    )
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    esito = egov_mod._richiedi_con_guardia("https://www.comune.marino.rm.it/", HOST, timeout=8.0)
    assert esito is not None
    pagina, url_finale = esito
    assert "EGSCHTST" in pagina
    assert url_finale == "https://www.comune.marino.rm.it/"


# --- Dispatcher (connettore.py:158) -------------------------------------


class _RispostaFinta:
    def __init__(self, headers: dict[str, str] | None = None, text: str = "") -> None:
        self.headers = headers or {}
        self.text = text


class _SondaDispatcherFinta:
    """Doppio minimale di `_Sonda`: solo `risposta`, come context manager
    (stesso stampo di `test_connettore_contratto.py`)."""

    def __init__(self, *, timeout: float = 8.0) -> None:
        self.timeout = timeout

    def __enter__(self) -> "_SondaDispatcherFinta":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def risposta(self, _url: str) -> _RispostaFinta:
        return _RispostaFinta(headers={}, text=_HOME_MARINO)


def test_dispatcher_instrada_egov_a_leggi_egov(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaDispatcherFinta)

    atteso = EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma=Piattaforma.EGOV.value,
        letto_il="2026-01-01T00:00:00+00:00",
        amministrazione_trasparente=AmministrazioneTrasparente(indice_url="https://x/at"),
    )
    fake_mod = types.ModuleType("treasureiq.egov")
    fake_mod.leggi_egov = lambda comune, sonda: atteso
    monkeypatch.setitem(sys.modules, "treasureiq.egov", fake_mod)

    esito = leggi_connettore(ISTAT, usa_cache=False)
    assert esito is atteso


def test_dispatcher_egov_non_importabile_ritorna_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """`treasureiq.egov` non importabile: nessun crash, `None` — stesso
    ramo deferred di Municipium (D-09 A9)."""
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaDispatcherFinta)
    monkeypatch.setitem(sys.modules, "treasureiq.egov", None)  # forza ImportError

    assert leggi_connettore(ISTAT, usa_cache=False) is None


# --- leggi_egov: scheletro, degrado D-10 --------------------------------


def test_leggi_egov_scheletro_ritorna_esito_con_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """B4b: nessun argomento reale in questo markup sintetico → fallback al
    degrado D-10 grezzo per `aree_amministrative`; l'indice AT si riconosce
    dal testo dell'ancora e viene REALMENTE seguito (un hop in più rispetto
    a B4a: home + indice AT), ma questo markup non ha "Bandi di concorso"
    → la catena AT si ferma lì con solo `indice_url` — mai un guscio rotto.
    Il doppio `_ClientFinto` risponde con la STESSA pagina home a QUALUNQUE
    url (anche l'indice uffici): nessun `ufficio_\\d+.html` in quel markup
    → `uffici` resta `[]`, ma il fetch avviene ed è contato (3 richieste)."""
    stream = _StreamFinto(
        200, "https://www.comune.marino.rm.it/", {}, [_HOME_MARINO.encode("utf-8")]
    )
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    sonda = _SondaFinta()
    esito = egov_mod.leggi_egov(_comune(), sonda)

    assert esito.piattaforma == Piattaforma.EGOV.value
    assert esito.uffici == []
    assert len(esito.aree_amministrative) >= 2
    assert esito.amministrazione_trasparente is not None
    assert "EGSATTRASP" in (esito.amministrazione_trasparente.indice_url or "")
    assert esito.amministrazione_trasparente.bandi_attivi == []
    assert sonda.richieste == 3
    assert sonda.raggiungibile is True


def test_leggi_egov_comune_senza_sito_esito_vuoto_onesto() -> None:
    esito = egov_mod.leggi_egov(_comune(sito=None), _SondaFinta())
    assert esito.piattaforma == Piattaforma.EGOV.value
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None
    assert esito.aree_amministrative == []


def test_leggi_egov_rete_muta_esito_vuoto_onesto_mai_eccezione(monkeypatch: pytest.MonkeyPatch) -> None:
    def _guasto(**_kwargs: object):
        raise RuntimeError("rete giu'")

    monkeypatch.setattr(egov_mod.httpx, "Client", _guasto)

    esito = egov_mod.leggi_egov(_comune(), _SondaFinta())
    assert esito.piattaforma == Piattaforma.EGOV.value
    assert esito.aree_amministrative == []
    assert esito.amministrazione_trasparente is None


# --- Fixture reali Marino (B4b, CK-3: markup non verificabile a tavolino) --

_FIXTURES = Path(__file__).parent / "fixtures"
_BASE_MARINO = "https://www.comune.marino.rm.it"


def _leggi_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text("utf-8")


def test_estrai_argomenti_home_marino_reale() -> None:
    """La home reale linka ~12 pagine-argomento (`EGSCHTST45.HBL?ARG=N`),
    non lo scheletro sintetico `EGSCHTST.HBL?en=eg###` — dati reali, non
    inventati a tavolino (CK-3)."""
    pagina = _leggi_fixture("egov_home_marino.html")
    aree = egov_mod._estrai_argomenti(pagina, _BASE_MARINO, HOST)
    assert len(aree) >= 10
    nomi = {area.nome for area in aree}
    assert "Istruzione" in nomi
    assert all("ARG=" in area.url for area in aree)
    assert all(area.url.startswith(_BASE_MARINO) for area in aree)


def test_area_mappa_home_marino_reale_id_letto_non_hardcoded() -> None:
    """L'id `en=eg176` si legge dalla pagina — la stessa pagina con un id
    diverso deve produrre un URL diverso (mai un letterale fisso)."""
    pagina = _leggi_fixture("egov_home_marino.html")
    area = egov_mod._area_mappa(pagina, _BASE_MARINO, HOST)
    assert area is not None
    assert area.url == "https://www.comune.marino.rm.it/EG0/EGSMISTMSIT.HBL?en=eg176&FUNZ=1"

    area_altro_id = egov_mod._area_mappa("...en=eg999...", _BASE_MARINO, HOST)
    assert area_altro_id is not None
    assert "en=eg999" in area_altro_id.url


def test_cerca_link_at_home_marino_reale_non_e_famiglia_egs() -> None:
    """Il link AT reale di Marino è una pagina statica fuori famiglia EGS
    (`/amministrazione/trasparenza/...`): si trova per TESTO dell'anchor,
    non per pattern URL — `_estrai_aree_egov` (pattern-URL) non lo vedrebbe
    mai."""
    pagina = _leggi_fixture("egov_home_marino.html")
    ancore = egov_mod._ancore(pagina, _BASE_MARINO, HOST)
    indice_url = egov_mod._cerca_link(ancore, egov_mod._RE_AT_TESTO)
    assert indice_url == "https://www.comune.marino.rm.it/amministrazione/trasparenza/trasparenza.html"
    assert not egov_mod._RE_ARG_URL.search(indice_url)


def test_cerca_link_concorso_e_aperti_catena_reale() -> None:
    """I due hop successivi della catena AT, sulle pagine reali: AT →
    "Bandi di concorso" → "…aperti"."""
    pagina_at = _leggi_fixture("egov_at_marino.html")
    ancore_at = egov_mod._ancore(pagina_at, _BASE_MARINO, HOST)
    concorso_url = egov_mod._cerca_link(ancore_at, egov_mod._RE_CONCORSO_TESTO)
    assert concorso_url is not None
    assert "EGSCHTST48" in concorso_url

    pagina_concorso = _leggi_fixture("egov_bandi_marino.html")
    ancore_concorso = egov_mod._ancore(pagina_concorso, concorso_url, HOST)
    aperti_url = egov_mod._cerca_link(ancore_concorso, egov_mod._RE_APERTI_TESTO)
    assert aperti_url is not None
    assert "EGSCHTST49" in aperti_url


def test_estrai_bandi_aperti_marino_reale_zero_onesto() -> None:
    """Oggi Marino non ha bandi di concorso aperti ("Nessun elemento
    estratto" nel blocco `#latest-posts`, osservato reale) — lista vuota
    LEGITTIMA, non un degrado: la distinzione conta (D-07)."""
    pagina = _leggi_fixture("egov_bandi_aperti_marino.html")
    bandi, pdf_presenti = egov_mod._estrai_bandi_aperti(pagina, _BASE_MARINO, HOST)
    assert bandi == []
    assert pdf_presenti is False


def test_estrai_bandi_aperti_ignora_feedback_widget_fuori_blocco() -> None:
    """La card-teaser del widget di rating, sotto `#latest-posts`, condivide
    la classe CSS con una card-bando ma è FUORI dal blocco delimitato — non
    deve mai apparire come bando (falso "bando spacciato per feedback")."""
    pagina = _leggi_fixture("egov_bandi_aperti_marino.html")
    blocco = egov_mod._blocco_latest_posts(pagina)
    assert blocco is not None
    assert "shadow-rating" not in blocco


def test_leggi_uffici_egov_indice_reale_marino(monkeypatch: pytest.MonkeyPatch) -> None:
    """Indice statico reale di Marino (`egov_uffici_marino.html`, 58 uffici
    osservati): estrazione index-only, nome+url, MAI recapiti (deferred,
    on-demand) — `source_typed=False` per ogni voce."""
    pagina_uffici = _leggi_fixture("egov_uffici_marino.html")
    uffici_url = _BASE_MARINO + "/EG0/EGSCHTST24.HBL?en=eg176&MESSA=PUBBLICA"
    stream = _StreamFinto(200, uffici_url, {}, [pagina_uffici.encode("utf-8")])
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    sonda = _SondaFinta()
    uffici = egov_mod._leggi_uffici_egov(_HOME_MARINO, _BASE_MARINO, HOST, sonda, 8.0)

    assert len(uffici) >= 1
    primo = uffici[0]
    assert primo.nome != ""
    assert re.search(r"ufficio_\d+\.html$", primo.url)
    assert primo.source_typed is False
    assert primo.telefoni == []
    assert primo.email == []
    assert primo.pec == []
    assert sonda.richieste == 1


def test_leggi_uffici_egov_senza_en_eg_ritorna_vuoto() -> None:
    """Markup senza `en=eg###`: nessun indice costruibile — `[]` onesto,
    zero fetch (nessuna sonda passata: se venisse chiamata il test
    fallirebbe per attributo mancante)."""
    uffici = egov_mod._leggi_uffici_egov("<html>niente qui</html>", _BASE_MARINO, HOST, None, 8.0)  # type: ignore[arg-type]
    assert uffici == []


def test_richiedi_con_guardia_mappa_reale_supera_cap_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """La mappa del sito reale di Marino pesa oltre `MAX_RISPOSTA_BYTES`
    (troncata a 2.1MB in fixture, ancora oltre il cap di 2MB): la guardia
    la aborta in streaming — degrado onesto per questa sola sezione, non un
    crash altrove."""
    contenuto = _leggi_fixture("egov_mappa_marino.html").encode("utf-8")
    assert len(contenuto) > egov_mod.MAX_RISPOSTA_BYTES
    mappa_url = _BASE_MARINO + "/EG0/EGSMISTMSIT.HBL?en=eg176&FUNZ=1"
    stream = _StreamFinto(200, mappa_url, {}, [contenuto])
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs))

    esito = egov_mod._richiedi_con_guardia(mappa_url, HOST, timeout=8.0)
    assert esito is None


class _ClientPerUrl:
    """Doppio di `httpx.Client` che risponde secondo l'URL richiesto —
    serve a esercitare `leggi_egov` end-to-end sulla catena reale (home →
    AT → concorso → aperti), non su un singolo doppio fisso come
    `_ClientFinto`."""

    def __init__(self, mappa: dict[str, str], **_kwargs: object) -> None:
        self._mappa = mappa

    def __enter__(self) -> "_ClientPerUrl":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def stream(self, _method: str, url: str) -> _StreamFinto:
        for prefisso, pagina in self._mappa.items():
            if url.startswith(prefisso):
                return _StreamFinto(200, url, {}, [pagina.encode("utf-8")])
        return _StreamFinto(404, url, {}, [])


def test_leggi_egov_end_to_end_fixture_reali_marino(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query reale end-to-end sulle fixture Marino: argomenti REALI (non
    generici), mappa come link noto (endpoint costruito dall'id letto),
    AT con indice reale e bandi-aperti a zero onesto, uffici come indice
    reale (`egov_uffici_marino.html`) — degrado PER-SEZIONE, non
    tutto-o-niente."""
    mappa_url = "https://www.comune.marino.rm.it/EG0/EGSMISTMSIT.HBL?en=eg176&FUNZ=1"
    uffici_url = "https://www.comune.marino.rm.it/EG0/EGSCHTST24.HBL?en=eg176&MESSA=PUBBLICA"
    pagine = {
        "https://www.comune.marino.rm.it/EG0/EGSCHTST48.HBL": _leggi_fixture("egov_bandi_marino.html"),
        "https://www.comune.marino.rm.it/EG0/EGSCHTST49.HBL": _leggi_fixture("egov_bandi_aperti_marino.html"),
        "https://www.comune.marino.rm.it/amministrazione/trasparenza/": _leggi_fixture("egov_at_marino.html"),
        mappa_url: "x" * (egov_mod.MAX_RISPOSTA_BYTES + 1),
        uffici_url: _leggi_fixture("egov_uffici_marino.html"),
        _BASE_MARINO: _leggi_fixture("egov_home_marino.html"),
    }
    monkeypatch.setattr(egov_mod.httpx, "Client", lambda **kwargs: _ClientPerUrl(pagine, **kwargs))

    sonda = _SondaFinta()
    esito = egov_mod.leggi_egov(_comune(), sonda)

    assert esito.piattaforma == Piattaforma.EGOV.value
    assert len(esito.uffici) > 0
    assert all(ufficio.url.endswith(".html") for ufficio in esito.uffici)
    assert all(ufficio.source_typed is False for ufficio in esito.uffici)

    nomi_aree = {area.nome for area in esito.aree_amministrative}
    assert "Istruzione" in nomi_aree
    assert any(area.nome == "Mappa del sito" and area.url == mappa_url for area in esito.aree_amministrative)

    at = esito.amministrazione_trasparente
    assert at is not None
    assert at.indice_url == "https://www.comune.marino.rm.it/amministrazione/trasparenza/trasparenza.html"
    assert at.bandi_attivi == []  # zero onesto: nessun bando aperto oggi (fixture reale)
    assert at.pdf_presenti is False

    # home + AT + concorso + aperti + uffici = 5 fetch guardati; mappa
    # supera il size-cap e viene abortita in streaming, MAI contata come
    # richiesta riuscita (stesso contatore-costo di `_Sonda`, D-08).
    assert sonda.richieste == 5
    assert sonda.raggiungibile is True
