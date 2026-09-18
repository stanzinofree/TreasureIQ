"""Per-domain pacing for the refresh path (429 burst fix).

The OpenPA/OpenCity refresh reads dozens of same-host sub-pages per comune and
the portals answer 429 to the burst. `PacerDominio` spaces same-domain GETs and
backs off on 429; a ContextVar scopes it to a refresh so the live chat path,
which shares `fetch_guardato`, keeps its unthrottled behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from treasureiq.ingest import fetch_pacing, host_guard
from treasureiq.ingest.censimento import _Sonda
from treasureiq.ingest.fetch_pacing import (
    PacerDominio,
    attiva_pacer,
    dominio_di,
    pacer_attivo,
    retry_after_secondi,
    ripristina_pacer,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _clock(monkeypatch, istante: list[datetime]) -> None:
    # Un orologio pilotabile: `istante[0]` è l'ora corrente, il test la avanza.
    monkeypatch.setattr(fetch_pacing, "_now", lambda: istante[0])


def _sleeps(monkeypatch) -> list[float]:
    dormite: list[float] = []
    monkeypatch.setattr(fetch_pacing.time, "sleep", lambda s: dormite.append(s))
    return dormite


# --- dominio_di -------------------------------------------------------------


@pytest.mark.parametrize(
    "url,atteso",
    [
        ("https://www.comune.x.it/a", "comune.x.it"),
        ("https://comune.x.it/a", "comune.x.it"),
        ("https://www.comune.x.it:8443/a", "comune.x.it"),
        ("https://user@www.comune.x.it/a", "comune.x.it"),
    ],
)
def test_dominio_di_normalizza(url: str, atteso: str) -> None:
    # www., porta e userinfo non fanno parte dell'identità da rispettare.
    assert dominio_di(url) == atteso


# --- PacerDominio.prima / dopo ---------------------------------------------


def test_prima_non_dorme_al_primo_colpo(monkeypatch) -> None:
    _clock(monkeypatch, [T0])
    dormite = _sleeps(monkeypatch)
    PacerDominio(intervallo_minimo_s=0.5).prima("https://c.it/x")
    assert dormite == []  # dominio mai visto: nessuna attesa


def test_prima_dorme_il_residuo_sullo_stesso_dominio(monkeypatch) -> None:
    istante = [T0]
    _clock(monkeypatch, istante)
    dormite = _sleeps(monkeypatch)
    pacer = PacerDominio(intervallo_minimo_s=0.5)
    pacer.dopo("https://c.it/a")  # registrato a T0
    istante[0] = T0 + timedelta(seconds=0.2)  # trascorsi 0.2s
    pacer.prima("https://www.c.it/b")  # stesso dominio (www ignorato)
    assert dormite == [pytest.approx(0.3)]  # residuo 0.5 - 0.2


def test_prima_non_dorme_su_dominio_diverso(monkeypatch) -> None:
    istante = [T0]
    _clock(monkeypatch, istante)
    dormite = _sleeps(monkeypatch)
    pacer = PacerDominio(intervallo_minimo_s=0.5)
    pacer.dopo("https://a.it/x")
    istante[0] = T0 + timedelta(seconds=0.01)
    pacer.prima("https://b.it/y")  # altro host: procede subito
    assert dormite == []


def test_prima_non_dorme_se_intervallo_gia_trascorso(monkeypatch) -> None:
    istante = [T0]
    _clock(monkeypatch, istante)
    dormite = _sleeps(monkeypatch)
    pacer = PacerDominio(intervallo_minimo_s=0.5)
    pacer.dopo("https://c.it/a")
    istante[0] = T0 + timedelta(seconds=1.0)  # oltre l'intervallo
    pacer.prima("https://c.it/b")
    assert dormite == []


def test_intervallo_zero_disattiva_il_pacing(monkeypatch) -> None:
    istante = [T0]
    _clock(monkeypatch, istante)
    dormite = _sleeps(monkeypatch)
    pacer = PacerDominio(intervallo_minimo_s=0.0)
    pacer.dopo("https://c.it/a")
    pacer.prima("https://c.it/b")
    assert dormite == []


# --- PacerDominio.backoff_429 ----------------------------------------------


def test_backoff_429_esponenziale_poi_si_arrende(monkeypatch) -> None:
    dormite = _sleeps(monkeypatch)
    pacer = PacerDominio(max_retry_429=2, backoff_base_s=2.0, backoff_cap_s=30.0)
    assert pacer.backoff_429("https://c.it", 0) is True  # 2.0
    assert pacer.backoff_429("https://c.it", 1) is True  # 4.0
    assert pacer.backoff_429("https://c.it", 2) is False  # esaurito: niente sleep
    assert dormite == [2.0, 4.0]


def test_backoff_429_onora_retry_after(monkeypatch) -> None:
    dormite = _sleeps(monkeypatch)
    pacer = PacerDominio(max_retry_429=3, backoff_base_s=2.0, backoff_cap_s=30.0)
    assert pacer.backoff_429("https://c.it", 0, retry_after_s=1.0) is True
    assert dormite == [1.0]  # header vince sull'esponenziale


def test_backoff_429_cappa_attesa(monkeypatch) -> None:
    dormite = _sleeps(monkeypatch)
    pacer = PacerDominio(max_retry_429=5, backoff_base_s=100.0, backoff_cap_s=10.0)
    assert pacer.backoff_429("https://c.it", 0) is True
    assert dormite == [10.0]  # 100 > cap 10


# --- retry_after_secondi ----------------------------------------------------


@pytest.mark.parametrize(
    "valore,atteso",
    [("5", 5.0), ("0", 0.0), ("  3 ", 3.0), (None, None), ("", None), ("abc", None), ("-1", None)],
)
def test_retry_after_secondi(valore, atteso) -> None:
    assert retry_after_secondi(valore) == atteso


# --- ContextVar -------------------------------------------------------------


def test_contextvar_default_none() -> None:
    assert pacer_attivo() is None


def test_attiva_e_ripristina() -> None:
    pacer = PacerDominio()
    token = attiva_pacer(pacer)
    try:
        assert pacer_attivo() is pacer
    finally:
        ripristina_pacer(token)
    assert pacer_attivo() is None


# --- integrazione: fetch_guardato consulta il pacer -------------------------


class _StreamFinto:
    def __init__(self, status_code: int, url: str, headers: dict, chunks: list[bytes]) -> None:
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

    def stream(self, method: str, url: str) -> _StreamFinto:
        return self._stream_resp


class _PacerSpia(PacerDominio):
    def __init__(self) -> None:
        super().__init__(intervallo_minimo_s=0.0)
        self.prima_viste: list[str] = []
        self.dopo_viste: list[str] = []
        self.backoff_viste: list[tuple[str, int, float | None]] = []

    def prima(self, url: str) -> None:
        self.prima_viste.append(url)

    def dopo(self, url: str) -> None:
        self.dopo_viste.append(url)

    def backoff_429(self, url: str, tentativo: int, retry_after_s: float | None = None) -> bool:
        self.backoff_viste.append((url, tentativo, retry_after_s))
        return tentativo < 1


def test_fetch_guardato_usa_il_pacer_attivo(monkeypatch) -> None:
    monkeypatch.setattr(host_guard, "host_risolve_a_ip_sicuro", lambda hostname: True)
    stream = _StreamFinto(200, "https://www.c.it/a", {"content-type": "text/html"}, [b"ok"])
    monkeypatch.setattr(host_guard.httpx, "Client", lambda **k: _ClientFinto(stream, **k))
    spia = _PacerSpia()
    token = attiva_pacer(spia)
    try:
        esito = host_guard.fetch_guardato("https://www.c.it/a", max_bytes=1000)
    finally:
        ripristina_pacer(token)
    assert esito is not None
    # prima+dopo chiamati intorno al GET guardato.
    assert spia.prima_viste == ["https://www.c.it/a"]
    assert spia.dopo_viste == ["https://www.c.it/a"]


def test_fetch_guardato_senza_pacer_non_rompe(monkeypatch) -> None:
    # Fuori da un refresh (pacer None) il path resta identico a prima.
    assert pacer_attivo() is None
    monkeypatch.setattr(host_guard, "host_risolve_a_ip_sicuro", lambda hostname: True)
    stream = _StreamFinto(200, "https://www.c.it/a", {}, [b"ok"])
    monkeypatch.setattr(host_guard.httpx, "Client", lambda **k: _ClientFinto(stream, **k))
    esito = host_guard.fetch_guardato("https://www.c.it/a", max_bytes=1000)
    assert esito is not None
    assert esito[1] == b"ok"


class _ClientStreamSequenza:
    def __init__(self, risposte: list[_StreamFinto], **_kwargs: object) -> None:
        self._risposte = risposte
        self.chiamate = 0

    def __enter__(self) -> "_ClientStreamSequenza":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def stream(self, method: str, url: str) -> _StreamFinto:
        risposta = self._risposte[min(self.chiamate, len(self._risposte) - 1)]
        self.chiamate += 1
        return risposta


def test_fetch_guardato_riprova_sul_429_sotto_pacer(monkeypatch) -> None:
    monkeypatch.setattr(host_guard, "host_risolve_a_ip_sicuro", lambda hostname: True)
    sequenza = _ClientStreamSequenza(
        [
            _StreamFinto(429, "https://www.c.it/a", {"retry-after": "3"}, []),
            _StreamFinto(200, "https://www.c.it/a", {"content-type": "text/html"}, [b"ok"]),
        ]
    )
    monkeypatch.setattr(host_guard.httpx, "Client", lambda **k: sequenza)
    spia = _PacerSpia()
    token = attiva_pacer(spia)
    try:
        esito = host_guard.fetch_guardato("https://www.c.it/a", max_bytes=1000)
    finally:
        ripristina_pacer(token)
    assert esito is not None
    assert esito[1] == b"ok"
    assert sequenza.chiamate == 2
    assert spia.backoff_viste == [("https://www.c.it/a", 0, 3.0)]
    assert spia.prima_viste == ["https://www.c.it/a", "https://www.c.it/a"]
    assert spia.dopo_viste == ["https://www.c.it/a", "https://www.c.it/a"]


# --- integrazione: _Sonda ripete sul 429 sotto pacer -----------------------


class _RespFinta:
    def __init__(self, status_code: int, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("errore", request=None, response=None)  # type: ignore[arg-type]


class _ClientSequenza:
    def __init__(self, risposte: list[_RespFinta]) -> None:
        self._risposte = risposte
        self.chiamate = 0

    def get(self, url: str, params: dict | None = None) -> _RespFinta:
        resp = self._risposte[min(self.chiamate, len(self._risposte) - 1)]
        self.chiamate += 1
        return resp

    def close(self) -> None:
        return None


def test_sonda_ripete_sul_429_sotto_pacer(monkeypatch) -> None:
    dormite = _sleeps(monkeypatch)
    sonda = _Sonda(timeout=1.0)
    sonda._client = _ClientSequenza([_RespFinta(429, {"retry-after": "1"}), _RespFinta(200)])
    token = attiva_pacer(PacerDominio(intervallo_minimo_s=0.0, max_retry_429=2))
    try:
        resp = sonda.risposta("https://c.it/a")
    finally:
        ripristina_pacer(token)
    assert resp.status_code == 200
    assert sonda._client.chiamate == 2  # 429 -> backoff -> ritenta -> 200
    assert dormite == [1.0]  # onora Retry-After


def test_sonda_senza_pacer_non_ripete(monkeypatch) -> None:
    # Fuori dal refresh: il 429 grezzo torna al chiamante (una sola GET).
    assert pacer_attivo() is None
    sonda = _Sonda(timeout=1.0)
    sonda._client = _ClientSequenza([_RespFinta(429), _RespFinta(200)])
    resp = sonda.risposta("https://c.it/a")
    assert resp.status_code == 429
    assert sonda._client.chiamate == 1
