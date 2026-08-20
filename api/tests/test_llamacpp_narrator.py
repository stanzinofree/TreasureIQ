import asyncio

import httpx

from treasureiq.chat.llamacpp import LlamaCppNarrator, NarrationContext


def _context() -> NarrationContext:
    return NarrationContext(
        deterministic_text="L'ufficio è aperto lunedì dalle 9 alle 12.",
        topic="anagrafe_carta_identita",
        kind="informazione",
        facts={"orario": "lunedì 09:00-12:00", "fonte": "connettore"},
    )


def test_fallback_deterministico_se_llamacpp_non_risponde():
    async def scenario():
        narrator = LlamaCppNarrator(base_url="http://127.0.0.1:1", timeout=0.1)
        return await narrator.narrate(_context())

    result = asyncio.run(scenario())
    assert result.used_fallback is True
    assert result.text == _context().deterministic_text


def test_prompt_include_solo_il_contratto_gia_risolto():
    prompt = LlamaCppNarrator._build_prompt(_context())
    assert "NON cambiare" in prompt
    assert "lunedì 09:00-12:00" in prompt
    assert "Risposta:" in prompt

