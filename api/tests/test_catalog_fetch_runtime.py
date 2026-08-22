"""Fase 2D-v — EsecutoreFetch: aggancio della PoliticaFetch a fetch_guardato.

Orologio e sleep sono iniettati: si verifica *quanto* si è aspettato e *cosa* è
stato chiamato, senza dormire e senza rete.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from treasureiq.catalog import fetch_runtime
from treasureiq.catalog.fetch_policy import PoliticaFetch
from treasureiq.catalog.fetch_runtime import EsecutoreFetch

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
