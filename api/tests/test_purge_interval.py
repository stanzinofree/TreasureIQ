"""F3: TREASUREIQ_CONVERSATION_PURGE_INTERVAL negativo = misconfig, fail-fast.

Solo ``0`` disabilita il loop periodico (il purge all'avvio resta); un intero
``> 0`` e' l'intervallo. Un valore negativo non e' un secondo modo per spegnere
il loop: l'avvio deve abortire invece di saltare in silenzio la sweep.

I test pilotano il globale del modulo via monkeypatch (come R2) ed entrano nel
lifespan con ``TestClient``: la guardia e' nella validazione all'avvio.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from treasureiq import api


def test_intervallo_negativo_fail_fast(monkeypatch) -> None:
    monkeypatch.setattr(api, "CONVERSATION_PURGE_INTERVAL_SECONDS", -1)
    with pytest.raises(RuntimeError, match="PURGE_INTERVAL negativo"):
        with TestClient(api.app):
            pass


def test_intervallo_zero_avvia_senza_loop(monkeypatch) -> None:
    # 0 = loop disabilitato (documentato), avvio regolare, nessun raise.
    monkeypatch.setattr(api, "CONVERSATION_PURGE_INTERVAL_SECONDS", 0)
    with TestClient(api.app):
        pass


def test_intervallo_positivo_avvia(monkeypatch) -> None:
    monkeypatch.setattr(api, "CONVERSATION_PURGE_INTERVAL_SECONDS", 3600)
    with TestClient(api.app):
        pass


def test_verifica_diretta_solo_su_negativo(monkeypatch) -> None:
    # Guardia a livello di funzione, indipendente dal lifespan.
    monkeypatch.setattr(api, "CONVERSATION_PURGE_INTERVAL_SECONDS", -5)
    with pytest.raises(RuntimeError):
        api._verifica_intervallo_purge()

    monkeypatch.setattr(api, "CONVERSATION_PURGE_INTERVAL_SECONDS", 0)
    api._verifica_intervallo_purge()  # 0 valido: nessun raise
