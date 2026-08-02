"""LLM provider abstraction: one async transport contract, two backends.

TreasureIQ runs extraction and chat against a local Ollama model by default —
the demo must work with no network and no API key, per the offline-build
commitment. Anthropic is kept as an optional fallback, selected purely by an
environment variable, so switching backends never touches call sites.

The contract is async-first on purpose: the chat route (`api.py`) awaits a
provider directly and must never block the event loop on a synchronous HTTP
call. `parse()` exists only for the ingestion CLI, which has no event loop of
its own to await into.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL_EXTRACT = "qwen3:14b"
DEFAULT_OLLAMA_MODEL_CHAT = "qwen3:4b"

ANTHROPIC_MODEL = "claude-opus-5"

# Extraction and chat are bounded reading/classification tasks, not
# reasoning problems: low effort keeps cost and latency down without
# measurably changing what gets recovered.
ANTHROPIC_EFFORT = "low"


@runtime_checkable
class LLMProvider(Protocol):
    """A backend that turns a system/user prompt pair into structured output.

    `aparse` is the single real method every provider implements, and the
    only one the async call paths (the FastAPI chat route) are allowed to
    use. `parse` is a thin synchronous wrapper kept for the ingestion CLI —
    never call it from an async context: it drives `aparse` through
    `asyncio.run`, which raises `RuntimeError` the moment an event loop is
    already running in the current thread.
    """

    name: str

    @property
    def available(self) -> bool:
        """Whether this provider can plausibly serve a request right now."""
        ...

    async def aparse(
        self, *, system: str, user: str, output_model: type[OutputModelT]
    ) -> OutputModelT:
        """Send one system/user turn and return a validated output_model."""
        ...

    def parse(
        self, *, system: str, user: str, output_model: type[OutputModelT]
    ) -> OutputModelT:
        """Synchronous wrapper for CLI/ingestion use only.

        Never call this from an async context — see the class docstring.
        """
        ...


class _SyncParseMixin:
    """Implements `parse` once, on top of whatever `aparse` a provider has.

    Kept separate from the Protocol so the sync wrapper is written a single
    time instead of duplicated per provider.
    """

    async def aparse(
        self, *, system: str, user: str, output_model: type[OutputModelT]
    ) -> OutputModelT:
        raise NotImplementedError

    def parse(
        self, *, system: str, user: str, output_model: type[OutputModelT]
    ) -> OutputModelT:
        """Synchronous wrapper — CLI/ingestion use only, never from async code.

        `asyncio.run` raises `RuntimeError: asyncio.run() cannot be called
        from a running event loop` if this is called from inside `async def`
        code; the ingestion CLI is the only intended caller.
        """
        return asyncio.run(
            self.aparse(system=system, user=user, output_model=output_model)
        )


class OllamaProvider(_SyncParseMixin):
    """Local-first provider talking to an Ollama daemon over HTTP.

    Uses `httpx`, already a project dependency — no new requirement. Thinking
    is explicitly disabled on every call: qwen3 emits a reasoning preamble by
    default, which breaks schema-constrained output and adds latency for no
    benefit on a bounded extraction/classification task.
    """

    name = "ollama"

    def __init__(self, *, model: str, base_url: str | None = None) -> None:
        self.model = model
        self.base_url = base_url or os.environ.get(
            "OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL
        )

    @property
    def available(self) -> bool:
        # The local daemon is assumed reachable in every deployment target
        # this project runs on (dev host, or compose via
        # host.docker.internal). Connectivity failures surface as an
        # exception raised from `aparse`, not as `available is False` — there
        # is no cheap way to probe reachability without adding latency to
        # every provider selection.
        return True

    async def aparse(
        self, *, system: str, user: str, output_model: type[OutputModelT]
    ) -> OutputModelT:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": output_model.model_json_schema(),
            "stream": False,
            # qwen3 thinks by default; forcing it off is load-bearing, see
            # the class docstring.
            "think": False,
            "options": {"temperature": 0},
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=120.0) as client:
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()
        data = response.json()
        content = data["message"]["content"]
        return output_model.model_validate_json(content)


class AnthropicProvider(_SyncParseMixin):
    """Fallback provider against the Anthropic API.

    The SDK is imported lazily so importing this module — and therefore
    `treasureiq.extract.llm` — never requires `anthropic` to be installed.
    Without an API key `available` is False; that is not an error, it just
    means this provider cannot serve a request right now.
    """

    name = "anthropic"

    def __init__(self, *, model: str = ANTHROPIC_MODEL, api_key: str | None = None) -> None:
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client: Any | None = None

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # imported lazily so cache-only runs need no SDK

            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def aparse(
        self, *, system: str, user: str, output_model: type[OutputModelT]
    ) -> OutputModelT:
        client = self._get_client()
        response = await client.messages.parse(
            model=self.model,
            max_tokens=4096,
            output_config={"effort": ANTHROPIC_EFFORT},
            # The system prompt is identical across every call in a run, so
            # caching it turns a per-call cost into a one-off. The volatile
            # part (the user turn) goes after the breakpoint, which is what
            # keeps the cached prefix stable.
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
            output_format=output_model,
        )

        if response.stop_reason == "refusal":
            raise RuntimeError(
                f"request refused: {getattr(response.stop_details, 'category', None)}"
            )
        if response.parsed_output is None:
            raise RuntimeError(f"no parsed output (stop_reason={response.stop_reason})")
        return response.parsed_output


def load_provider(*, role: Literal["extract", "chat"]) -> LLMProvider:
    """Build the provider configured by `TREASUREIQ_LLM_PROVIDER` (default `ollama`).

    `role` only selects which Ollama model is used (extraction and chat are
    sized differently); Anthropic uses one model regardless of role,
    unchanged from the pre-existing extraction-only behaviour.
    """
    backend = os.environ.get("TREASUREIQ_LLM_PROVIDER", "ollama").strip().lower()

    if backend == "anthropic":
        return AnthropicProvider()

    if backend == "ollama":
        if role == "extract":
            env_var, default_model = (
                "TREASUREIQ_OLLAMA_MODEL_EXTRACT",
                DEFAULT_OLLAMA_MODEL_EXTRACT,
            )
        else:
            env_var, default_model = (
                "TREASUREIQ_OLLAMA_MODEL_CHAT",
                DEFAULT_OLLAMA_MODEL_CHAT,
            )
        model = os.environ.get(env_var, default_model)
        return OllamaProvider(model=model)

    raise ValueError(f"unknown TREASUREIQ_LLM_PROVIDER: {backend!r}")
