"""GameBook-style civic engine tests."""

import asyncio

import pytest

from treasureiq.chat.engine import (
    _BACKEND_DETERMINISTICI,
    _DEFAULT_BACKEND,
    CivicChatEngine,
)
from treasureiq.chat.intent import Topic
from treasureiq.chat.llamacpp import load_narrator


class _ProviderMustNotRun:
    async def aparse(self, **_kwargs):  # pragma: no cover - failure path
        raise AssertionError("the deterministic engine must not call a provider")


def test_engine_deterministico_emette_il_contratto_senza_provider():
    result = asyncio.run(
        CivicChatEngine(backend="scorer").analyse(
            message="quali sono gli orari dell'ufficio anagrafe di Albano Laziale?",
            provider=_ProviderMustNotRun(),
        )
    )

    assert result.deterministic is True
    assert result.backend == "scorer"
    assert result.recognition.version == "v1"
    assert result.intent.topic is Topic.ANAGRAFE_CARTA_IDENTITA
    assert result.recognition.municipality_explicit is False


def test_engine_conserva_filtri_e_contesto_nel_contratto():
    result = asyncio.run(
        CivicChatEngine(backend="scorer").analyse(
            message="ho 38 anni e un ISEE di 12.000 euro",
            storia=["cerco un contributo per la mensa ad Albano"],
        )
    )

    assert result.recognition.context_turns == 1
    assert "eta" in result.recognition.filter_keys
    assert "isee" in result.recognition.filter_keys


# --- R4: default sicuro + guardia produzione sul rail model ---


def _pulisci_env_backend(monkeypatch) -> None:
    monkeypatch.delenv("TREASUREIQ_ENGINE_INTENT_BACKEND", raising=False)
    monkeypatch.delenv("TREASUREIQ_INTENT_BACKEND", raising=False)
    monkeypatch.delenv("TREASUREIQ_ENV", raising=False)


def test_default_backend_e_deterministico(monkeypatch) -> None:
    # Senza scelta esplicita, il codice resta sul rail deterministico: nessun
    # provider, nessun egress. Il default non e' piu' "model".
    _pulisci_env_backend(monkeypatch)
    engine = CivicChatEngine()
    assert engine.backend == _DEFAULT_BACKEND
    assert engine.backend in _BACKEND_DETERMINISTICI
    assert engine.deterministic is True


def test_produzione_vieta_backend_model_fail_fast(monkeypatch) -> None:
    _pulisci_env_backend(monkeypatch)
    monkeypatch.setenv("TREASUREIQ_ENV", "production")
    with pytest.raises(RuntimeError, match="non e' autorizzato"):
        CivicChatEngine(backend="model")


def test_produzione_consente_rail_deterministico(monkeypatch) -> None:
    _pulisci_env_backend(monkeypatch)
    monkeypatch.setenv("TREASUREIQ_ENV", "production")
    engine = CivicChatEngine(backend="scorer")  # nessun raise
    assert engine.deterministic is True


def test_sviluppo_consente_backend_model(monkeypatch) -> None:
    # Fallback di sviluppo: fuori produzione il rail model resta usabile.
    _pulisci_env_backend(monkeypatch)
    engine = CivicChatEngine(backend="model")
    assert engine.backend == "model"
    assert engine.deterministic is False


def test_narrator_esterno_disabilitato_di_default(monkeypatch) -> None:
    monkeypatch.delenv("TREASUREIQ_NARRATOR_BACKEND", raising=False)
    assert load_narrator() is None
