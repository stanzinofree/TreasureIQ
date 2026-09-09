"""R2: in produzione il cookie di sessione DEVE essere Secure.

Una produzione con Secure spento e' una config incoerente: l'avvio deve
abortire (fail-fast), non degradare in silenzio a un cookie in chiaro. Lo
sviluppo locale su http://localhost resta permesso senza Secure.

I test pilotano i flag d'ambiente via monkeypatch sui globali del modulo
(`IS_PRODUCTION`, `COOKIE_SECURE`) ed entrano nel lifespan con ``TestClient``:
il fail-fast e' proprio nella validazione all'avvio.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from treasureiq import api


def test_production_con_secure_avvia(monkeypatch) -> None:
    monkeypatch.setattr(api, "IS_PRODUCTION", True)
    monkeypatch.setattr(api, "COOKIE_SECURE", True)
    # Nessun raise: l'app entra e esce dal lifespan normalmente.
    with TestClient(api.app):
        pass


def test_production_senza_secure_fail_fast(monkeypatch) -> None:
    monkeypatch.setattr(api, "IS_PRODUCTION", True)
    monkeypatch.setattr(api, "COOKIE_SECURE", False)
    with pytest.raises(RuntimeError, match="TREASUREIQ_COOKIE_SECURE=1"):
        with TestClient(api.app):
            pass


def test_sviluppo_senza_secure_avvia(monkeypatch) -> None:
    # Sviluppo locale su http://localhost: Secure spento resta valido.
    monkeypatch.setattr(api, "IS_PRODUCTION", False)
    monkeypatch.setattr(api, "COOKIE_SECURE", False)
    with TestClient(api.app):
        pass


def test_verifica_diretta_solleva_solo_in_produzione_insecura(monkeypatch) -> None:
    # Guardia a livello di funzione, indipendente dal lifespan.
    monkeypatch.setattr(api, "IS_PRODUCTION", True)
    monkeypatch.setattr(api, "COOKIE_SECURE", False)
    with pytest.raises(RuntimeError):
        api._verifica_coerenza_cookie()

    monkeypatch.setattr(api, "COOKIE_SECURE", True)
    api._verifica_coerenza_cookie()  # produzione coerente: nessun raise
