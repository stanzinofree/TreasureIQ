"""R5: egress esplicito verso provider esterni.

Tre superfici distinte (vedi il docstring di ``providers``): Ollama e llama.cpp
sono locali, Anthropic e' l'unica che lascia la macchina. Questi test bloccano:

- il default resta locale (nessun egress senza sceglierlo);
- il provider esterno non si costruisce senza consenso esplicito (fail-fast);
- sul rail model il payload inviato e' esattamente messaggio + storia
  etichettata e delimitata (nessun contrabbando di altro contesto);
- il rail deterministico non chiama alcun provider.
"""

from __future__ import annotations

import asyncio

import pytest

from treasureiq.chat.intent import (
    INTENT_SYSTEM_PROMPT,
    Topic,
    _ModelIntent,
    extract_intent,
)
from treasureiq.extract.providers import (
    EXTERNAL_LLM_ACK_ENV,
    AnthropicProvider,
    OllamaProvider,
    _assicura_egress_autorizzato,
    load_provider,
)


def _pulisci_env_provider(monkeypatch) -> None:
    monkeypatch.delenv("TREASUREIQ_LLM_PROVIDER", raising=False)
    monkeypatch.delenv(EXTERNAL_LLM_ACK_ENV, raising=False)


class _ProviderCattura:
    """Stub che registra il payload invece di uscire in rete."""

    name = "cattura"
    external_egress = False

    def __init__(self) -> None:
        self.chiamate: list[dict[str, object]] = []

    async def aparse(self, *, system, user, output_model):
        self.chiamate.append({"system": system, "user": user})
        return _ModelIntent(topic=Topic.SCONOSCIUTO)


class _ProviderVietato:
    name = "vietato"
    external_egress = False

    async def aparse(self, **_kwargs):  # pragma: no cover - percorso di errore
        raise AssertionError("il rail deterministico non deve chiamare un provider")


# --- superfici e default ---


def test_default_provider_e_locale_niente_egress(monkeypatch) -> None:
    _pulisci_env_provider(monkeypatch)
    provider = load_provider(role="chat")
    assert isinstance(provider, OllamaProvider)
    assert provider.external_egress is False


def test_anthropic_e_marcato_egress_esterno() -> None:
    assert AnthropicProvider.external_egress is True
    assert OllamaProvider.external_egress is False


# --- gate egress esterno ---


def test_provider_esterno_senza_consenso_fail_fast(monkeypatch) -> None:
    _pulisci_env_provider(monkeypatch)
    monkeypatch.setenv("TREASUREIQ_LLM_PROVIDER", "anthropic")
    with pytest.raises(RuntimeError, match=EXTERNAL_LLM_ACK_ENV):
        load_provider(role="chat")


def test_provider_esterno_con_consenso_esplicito(monkeypatch) -> None:
    _pulisci_env_provider(monkeypatch)
    monkeypatch.setenv("TREASUREIQ_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv(EXTERNAL_LLM_ACK_ENV, "1")
    provider = load_provider(role="chat")
    assert isinstance(provider, AnthropicProvider)
    assert provider.external_egress is True


# --- payload del rail model: delimitato e limitato ---


def test_rail_model_delimita_messaggio_e_storia() -> None:
    provider = _ProviderCattura()
    storia = ["primo turno", "secondo turno", "terzo turno", "quarto turno"]
    asyncio.run(
        extract_intent(
            message="e per lo scuolabus?",
            provider=provider,
            storia=storia,
            backend="model",
        )
    )

    assert len(provider.chiamate) == 1
    inviato = provider.chiamate[0]
    assert inviato["system"] == INTENT_SYSTEM_PROMPT
    user = inviato["user"]
    # Il messaggio da classificare e' delimitato ed etichettato...
    assert "Messaggio da classificare: e per lo scuolabus?" in user
    assert "Turni precedenti del cittadino" in user
    # ...e solo gli ultimi 3 turni escono: il primo resta a terra.
    assert "primo turno" not in user
    assert "secondo turno" in user
    assert "quarto turno" in user


# --- F2: gate egress applicato al provider, non solo alla factory ---


def test_helper_blocca_provider_esterno_senza_consenso(monkeypatch) -> None:
    monkeypatch.delenv(EXTERNAL_LLM_ACK_ENV, raising=False)
    with pytest.raises(RuntimeError, match=EXTERNAL_LLM_ACK_ENV):
        _assicura_egress_autorizzato(AnthropicProvider(api_key="x"))


def test_helper_consente_provider_esterno_con_consenso(monkeypatch) -> None:
    monkeypatch.setenv(EXTERNAL_LLM_ACK_ENV, "1")
    _assicura_egress_autorizzato(AnthropicProvider(api_key="x"))  # nessun raise


def test_helper_ignora_provider_locale(monkeypatch) -> None:
    monkeypatch.delenv(EXTERNAL_LLM_ACK_ENV, raising=False)
    _assicura_egress_autorizzato(OllamaProvider(model="qwen3:4b"))  # locale: mai raise


def test_aparse_esterno_diretto_fail_fast_prima_della_rete(monkeypatch) -> None:
    # Bypass della factory: si istanzia il provider esterno direttamente. La
    # guardia in aparse deve scattare PRIMA di qualsiasi contatto con l'SDK
    # (nessun anthropic installato serve). api_key presente per isolare che a
    # fermare la chiamata sia il gate egress, non la mancanza di credenziale.
    monkeypatch.delenv(EXTERNAL_LLM_ACK_ENV, raising=False)
    provider = AnthropicProvider(api_key="x")
    with pytest.raises(RuntimeError, match=EXTERNAL_LLM_ACK_ENV):
        asyncio.run(
            provider.aparse(system="s", user="u", output_model=_ModelIntent)
        )


def test_rail_deterministico_non_invia_nessun_payload() -> None:
    provider = _ProviderVietato()
    # backend scorer: nessuna aparse, nessun egress. Se il provider fosse
    # chiamato l'AssertionError verrebbe inghiottita da extract_intent, quindi
    # verifichiamo l'esito deterministico invece dell'assenza di raise.
    intent = asyncio.run(
        extract_intent(
            message="quali sono gli orari dell'ufficio anagrafe?",
            provider=provider,
            backend="scorer",
        )
    )
    assert intent.topic is Topic.ANAGRAFE_CARTA_IDENTITA
