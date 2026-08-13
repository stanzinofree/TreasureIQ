"""`extract_intent` col backend scorer (`TREASUREIQ_INTENT_BACKEND=scorer`).

Prova due cose:
  1. il modello NON viene chiamato (il provider finto esplode se toccato);
  2. l'esito topic/kind coincide con l'oracolo `score_intent`, e la cintura
     deterministica a valle (R-8, _confirm_*) resta invariata.

Il default resta "model": questi test forzano il ramo scorer via monkeypatch
della costante di modulo, letta una sola volta all'import.
"""
import asyncio
import json
from pathlib import Path

import pytest

from treasureiq.chat import intent as intent_mod
from treasureiq.chat.intent import BeneficiaryRole, QuestionKind, Topic, extract_intent
from treasureiq.chat.intent_scorer import score_intent

_CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "tiq_intent" / "cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


class _ProviderCheEsplode:
    """Col backend scorer nessuna chiamata al modello deve partire: se
    `aparse` viene invocato, il test fallisce forte invece di passare in
    silenzio ripiegando sul modello."""

    async def aparse(self, *, system, user, output_model):
        raise AssertionError("backend scorer non deve chiamare il modello")


@pytest.fixture
def backend_scorer(monkeypatch):
    monkeypatch.setattr(intent_mod, "_INTENT_BACKEND", "scorer")


@pytest.mark.parametrize("caso", _CASES, ids=lambda c: c["msg"][:40] or "<vuoto>")
def test_extract_intent_scorer_riproduce_lo_scorer(caso, backend_scorer):
    atteso = score_intent(caso["msg"])
    intent = asyncio.run(
        extract_intent(message=caso["msg"], provider=_ProviderCheEsplode())
    )
    assert intent.topic == Topic(atteso.topic)
    assert intent.kind == QuestionKind(atteso.kind)


@pytest.fixture
def backend_rust(monkeypatch):
    monkeypatch.setattr(intent_mod, "_INTENT_BACKEND", "rust")


@pytest.mark.parametrize("caso", _CASES, ids=lambda c: c["msg"][:40] or "<vuoto>")
def test_extract_intent_rust_ha_parita_con_lo_scorer(caso, backend_rust):
    # Il crate nativo esiste solo nell'immagine con la wheel: fuori (host,
    # immagine senza Rust) si salta. Dentro, deve dare lo stesso esito del
    # backend scorer Python (parità 35/35 = l'oracolo è lo stesso).
    pytest.importorskip("tiq_intent")
    atteso = score_intent(caso["msg"])
    intent = asyncio.run(
        extract_intent(message=caso["msg"], provider=_ProviderCheEsplode())
    )
    assert intent.topic == Topic(atteso.topic)
    assert intent.kind == QuestionKind(atteso.kind)


def test_scorer_non_inventa_un_comune(backend_scorer):
    # Lo scorer non tocca il comune: resta None, lo risolve il testo a valle.
    intent = asyncio.run(
        extract_intent(
            message="orari ufficio anagrafe", provider=_ProviderCheEsplode()
        )
    )
    assert intent.comune_hint is None


def test_ruolo_volontario_dai_marcatori(backend_scorer):
    # «voglio fare volontariato» dichiara il ruolo nel testo -> VOLONTARIO,
    # esattamente ciò che _confirm_beneficiary_role terrebbe col modello.
    intent = asyncio.run(
        extract_intent(
            message="voglio fare volontariato con gli anziani",
            provider=_ProviderCheEsplode(),
        )
    )
    assert intent.beneficiary_role is BeneficiaryRole.VOLONTARIO


def test_ruolo_vuoto_se_solo_ricerca(backend_scorer):
    # «cerco un servizio di volontariato per anziani» è una ricerca, non una
    # dichiarazione di ruolo: nessun marcatore -> None (non si indovina).
    intent = asyncio.run(
        extract_intent(
            message="cerco un servizio di volontariato per anziani",
            provider=_ProviderCheEsplode(),
        )
    )
    assert intent.beneficiary_role is None
