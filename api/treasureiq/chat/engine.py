"""Deterministic civic chat engine.

This is the TIQ equivalent of GameBook's semantic engine. A provider may
understand language, but it never owns routing, retrieval or the answer:

    analyse -> validate -> recognition contract -> QueryPlan -> retrieval

The existing intent guards and filter recogniser remain the implementation
behind this seam. Production selects ``rust``; the Rust scorer falls back to
the equivalent Python scorer when its wheel is not present. ``model`` remains
an explicit compatibility/upgrade path, not a requirement for TIQ to run.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from treasureiq.chat.intent import (
    ChatIntent,
    ChatRecognitionContract,
    build_recognition_contract,
    extract_intent,
)
from treasureiq.chat.llamacpp import NarrationContext, NarrationResult, load_narrator
from treasureiq.extract.providers import LLMProvider, load_provider


@dataclass(frozen=True)
class EngineAnalysis:
    """Validated result of one citizen turn."""

    recognition: ChatRecognitionContract
    backend: str
    deterministic: bool

    @property
    def intent(self) -> ChatIntent:
        return self.recognition.intent


class CivicChatEngine:
    """Own the understanding rail, while mechanics stay in the planner."""

    def __init__(self, *, backend: str | None = None) -> None:
        engine_env = os.environ.get("TREASUREIQ_ENGINE_INTENT_BACKEND")
        intent_env = os.environ.get("TREASUREIQ_INTENT_BACKEND")
        # Se entrambe le env sono settate e disaccordano, il backend effettivo
        # e' quello dell'engine (precedenza), ma il disaccordo silenzioso e' un
        # rischio: lo si segnala una volta, non e' un errore.
        if (
            backend is None
            and engine_env is not None
            and intent_env is not None
            and engine_env.strip().lower() != intent_env.strip().lower()
        ):
            logging.getLogger(__name__).warning(
                "intent backend env in disaccordo: TREASUREIQ_ENGINE_INTENT_BACKEND=%r "
                "(vince) vs TREASUREIQ_INTENT_BACKEND=%r",
                engine_env,
                intent_env,
            )
        self.backend = (
            backend
            or engine_env
            or intent_env
            or "model"
        ).strip().lower()

    @property
    def deterministic(self) -> bool:
        return self.backend in {"rust", "scorer"}

    async def analyse(
        self,
        *,
        message: str,
        storia: list[str] | None = None,
        provider: LLMProvider | None = None,
    ) -> EngineAnalysis:
        """Return one narrow recognition contract.

        The provider is loaded only on the explicit model rail. Rust/Python
        operation therefore has no Ollama dependency or network call.
        """

        selected_provider = provider
        if self.backend not in {"rust", "scorer"} and selected_provider is None:
            selected_provider = load_provider(role="chat")

        intent = await extract_intent(
            message=message,
            provider=selected_provider,  # type: ignore[arg-type]
            storia=storia,
            backend=self.backend,
        )
        recognition = build_recognition_contract(
            message=message, intent=intent, storia=storia
        )
        return EngineAnalysis(
            recognition=recognition,
            backend=self.backend,
            deterministic=self.deterministic,
        )

    async def narrate(self, context: NarrationContext) -> NarrationResult:
        """Optionally polish an already deterministic response.

        Disabled by default. The fallback is the exact deterministic text, so
        enabling the optional service can never become a source dependency.
        """

        narrator = load_narrator()
        if narrator is None:
            return NarrationResult(text=context.deterministic_text, used_fallback=True)
        return await narrator.narrate(context)


chat_engine = CivicChatEngine()
