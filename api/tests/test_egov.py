"""Test di `egov.py` (ciclo 14, brief B4a): niente rete — firma, dispatcher
e guardie isolate via monkeypatch, stesso stampo di `test_registro.py`
(`_StreamFinto`/`_ClientFinto`) e `test_connettore_contratto.py`
(dispatcher).

Fixture "Marino" (D-10, `.kapi/spec.md`): `en=eg176`, due endpoint distinti
osservati (`EGSCHTST.HBL` servizi, `EGSMISTMSIT.HBL` mappa) più un terzo
link "Amministrazione Trasparente" sintetico per verificare il degrado AT.
"""

from __future__ import annotations

import sys
import types

import pytest

import treasureiq.connettore as connettore_mod
import treasureiq.egov as egov_mod
from treasureiq.connettore import AmministrazioneTrasparente, EsitoConnettore, leggi_connettore
from treasureiq.ingest.piattaforma import Piattaforma, firma_da_risposta
from treasureiq.sonda_live import ComuneNoto

ISTAT = "058048"
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
    """Nessun parser (B4b non ancora scritto): gli endpoint riconosciuti
    diventano già oggi link nella card, e l'indice AT si riconosce dal
    testo dell'ancora — mai un guscio rotto."""
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
    assert sonda.richieste == 1
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
