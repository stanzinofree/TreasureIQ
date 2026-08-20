"""Optional llama.cpp verbalizer for the deterministic civic engine.

The contract mirrors GameBook: llama.cpp receives an already resolved answer
and may improve its tone, but it cannot choose the topic, source, numbers,
access mode or outcome. Any transport/validation failure returns the original
deterministic text.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping

import httpx


@dataclass(frozen=True)
class NarrationContext:
    """Facts already decided by TIQ, safe to hand to a verbalizer."""

    deterministic_text: str
    topic: str
    kind: str
    facts: Mapping[str, object]


@dataclass(frozen=True)
class NarrationResult:
    text: str
    used_fallback: bool
    error: str | None = None


class LlamaCppNarrator:
    """Async, prose-only llama.cpp adapter.

    It is intentionally not an ``LLMProvider``: structured intent extraction
    and ingestion extraction have a different contract. This adapter is only
    for a future, explicitly enabled response-polishing rail.
    """

    name = "llamacpp"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
        n_predict: int = 256,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("TREASUREIQ_LLAMACPP_URL")
            or "http://llama-cpp:8080"
        ).rstrip("/")
        self.timeout = timeout
        self.n_predict = n_predict

    async def narrate(self, context: NarrationContext) -> NarrationResult:
        prompt = self._build_prompt(context)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/completion",
                    json={
                        "prompt": prompt,
                        "n_predict": self.n_predict,
                        "temperature": 0.2,
                        "top_p": 0.9,
                        "stop": ["\n---FINE---"],
                    },
                )
                response.raise_for_status()
                raw = response.json().get("content", "")
            text = self._clean_output(raw, context.deterministic_text)
            if not text:
                raise ValueError("llama.cpp ha restituito testo vuoto")
            # Small/quantized instruct models occasionally copy the prompt or
            # its delimiters. That is not narration and must never leak into
            # the public answer: preserve the deterministic contract instead.
            if (
                "---INIZIO---" in text
                or "---FINE---" in text
                or "Testo deterministico da preservare:" in text
                or not any(character.isalnum() for character in text)
            ):
                return NarrationResult(
                    text=context.deterministic_text,
                    used_fallback=True,
                    error="llama.cpp ha riecheggiato il prompt",
                )
            return NarrationResult(text=text, used_fallback=False)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return NarrationResult(
                text=context.deterministic_text,
                used_fallback=True,
                error=str(exc),
            )

    @staticmethod
    def _clean_output(raw: str, deterministic_text: str) -> str:
        """Remove harmless response labels without altering civic facts."""

        text = raw.strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) >= 4 and len(set(lines)) == 1:
            return ""
        if text.startswith("Risposta:"):
            text = text[len("Risposta:") :].lstrip()
        # A model may include a markdown code fence around plain prose. Strip
        # only the fence, never the content inside it.
        if text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()
        # If the model simply repeats the deterministic answer, retain one
        # copy and treat it as a valid but unnecessary narration.
        if text == deterministic_text:
            return deterministic_text
        return text

    @staticmethod
    def _build_prompt(context: NarrationContext) -> str:
        facts = json.dumps(context.facts, ensure_ascii=False, sort_keys=True)
        return (
            "Sei il verbalizzatore di TIQ. Riscrivi in italiano chiaro e umano "
            "il testo deterministico ricevuto. NON cambiare, omettere o "
            "inventare nomi, numeri, date, fonti, livelli di accesso o esiti. "
            "NON aggiungere consigli non presenti. Produci solo il testo della "
            "risposta, senza prefazioni e senza markdown tecnico.\n"
            f"Argomento: {context.topic}\n"
            f"Tipo: {context.kind}\n"
            f"Fatti strutturati (sola lettura): {facts}\n"
            f"Testo deterministico da preservare: {context.deterministic_text}\n"
            "---FINE---\nRisposta:\n"
        )


def load_narrator() -> LlamaCppNarrator | None:
    """Load the optional narrator only when explicitly enabled."""

    if os.environ.get("TREASUREIQ_NARRATOR_BACKEND", "deterministic").strip().lower() \
        != "llamacpp":
        return None
    return LlamaCppNarrator()
