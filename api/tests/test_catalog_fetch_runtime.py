"""Fase 2D-v — EsecutoreFetch: aggancio della PoliticaFetch a fetch_guardato.

Orologio e sleep sono iniettati: si verifica *quanto* si è aspettato e *cosa* è
stato chiamato, senza dormire e senza rete.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import httpx

from treasureiq.catalog import fetch_runtime
from treasureiq.catalog.fetch_policy import PoliticaFetch
from treasureiq.catalog.fetch_runtime import EsecutoreFetch, EsecutoreFetchSerializzato

_T0 = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
_URL = "https://comune.example.it/at"


def _fetch_registratore(monkeypatch):
    chiamate: list[str] = []

    def fake(url, **_kw):
        chiamate.append(url)
        return httpx.Headers({}), b"<html></html>", url

    monkeypatch.setattr(fetch_runtime, "fetch_guardato", fake)
    return chiamate


def test_esegui_consente_fetch_e_registra(monkeypatch):
    chiamate = _fetch_registratore(monkeypatch)
    dormite: list[float] = []
    ese = EsecutoreFetch(
        PoliticaFetch(), orologio=lambda: _T0, dormi=dormite.append
    )

    esito = ese.esegui(_URL, max_bytes=1000)

    assert esito.consentito is True
    assert esito.fetched is not None
    assert chiamate == [_URL]
    assert dormite == []  # primo colpo: nessuna attesa


def test_budget_esaurito_non_scarica(monkeypatch):
    chiamate = _fetch_registratore(monkeypatch)
    ese = EsecutoreFetch(
        PoliticaFetch(massimo_per_dominio=1), orologio=lambda: _T0, dormi=lambda _s: None
    )

    ese.esegui(_URL, max_bytes=1000)  # consuma l'unico slot
    esito = ese.esegui("https://comune.example.it/altro", max_bytes=1000)

    assert esito.consentito is False
    assert esito.motivo == "budget_esaurito"
    assert chiamate == [_URL]  # secondo fetch mai eseguito


def test_backoff_dai_fallimenti_impone_attesa(monkeypatch):
    _fetch_registratore(monkeypatch)
    dormite: list[float] = []
    ese = EsecutoreFetch(
        PoliticaFetch(backoff_base_s=60.0, backoff_cap_s=3600.0),
        orologio=lambda: _T0, dormi=dormite.append,
    )

    esito = ese.esegui(_URL, fallimenti_consecutivi=1, max_bytes=1000)

    assert esito.consentito is True
    assert dormite == [60.0]  # 1 fallimento → backoff base


# --- coordinatore serializzato (Slice 5, D-S5-10) --------------------------


def test_serializzato_stesso_dominio_non_si_sovrappone(monkeypatch):
    # Il lock di dominio copre decidi→sleep→fetch→registra: due thread non devono
    # MAI essere dentro la sezione critica dello stesso dominio insieme.
    dentro = {"attivo": False}
    overlap = {"visto": False}

    def fake(url, **_kw):
        if dentro["attivo"]:
            overlap["visto"] = True
        dentro["attivo"] = True
        # piccola finestra per far collidere thread concorrenti se non serializzati
        for _ in range(1000):
            pass
        dentro["attivo"] = False
        return httpx.Headers({}), b"x", url

    monkeypatch.setattr(fetch_runtime, "fetch_guardato", fake)
    ese = EsecutoreFetchSerializzato(
        PoliticaFetch(massimo_per_dominio=100, intervallo_minimo_s=0.0),
        orologio=lambda: _T0,
        dormi=lambda _s: None,
    )
    threads = [
        threading.Thread(target=lambda: ese.esegui(_URL, max_bytes=1)) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlap["visto"] is False


def test_serializzato_budget_non_sovra_consumato(monkeypatch):
    # Sotto concorrenza il budget del dominio non deve essere sforato da una race
    # sulla decisione: esattamente `massimo` fetch reali, gli altri rifiutati.
    chiamate: list[str] = []
    lock = threading.Lock()

    def fake(url, **_kw):
        with lock:
            chiamate.append(url)
        return httpx.Headers({}), b"x", url

    monkeypatch.setattr(fetch_runtime, "fetch_guardato", fake)
    ese = EsecutoreFetchSerializzato(
        PoliticaFetch(massimo_per_dominio=3, intervallo_minimo_s=0.0),
        orologio=lambda: _T0,
        dormi=lambda _s: None,
    )
    esiti: list[bool] = []
    esiti_lock = threading.Lock()

    def worker():
        esito = ese.esegui(_URL, max_bytes=1)
        with esiti_lock:
            esiti.append(esito.consentito)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(esiti) == 3  # esattamente il budget concesso
    assert len(chiamate) == 3  # nessun fetch oltre il budget


def test_serializzato_lock_per_dominio_distinti():
    # Domini diversi hanno lock diversi (possono procedere in parallelo); lo
    # stesso dominio condivide lo stesso lock (serializzato).
    ese = EsecutoreFetchSerializzato(PoliticaFetch())
    a1 = ese._lock_per("https://a.it/x")
    a2 = ese._lock_per("https://a.it/y")
    b1 = ese._lock_per("https://b.it/z")
    assert a1 is a2
    assert a1 is not b1
