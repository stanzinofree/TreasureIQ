"""GameBook-style civic engine tests."""

import asyncio

from treasureiq.chat.engine import CivicChatEngine
from treasureiq.chat.intent import Topic


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
