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
import sys
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
    tiq_intent = pytest.importorskip("tiq_intent")
    if not hasattr(tiq_intent, "score"):
        pytest.skip("modulo tiq_intent presente senza estensione nativa score")
    atteso = score_intent(caso["msg"])
    intent = asyncio.run(
        extract_intent(message=caso["msg"], provider=_ProviderCheEsplode())
    )
    assert intent.topic == Topic(atteso.topic)
    assert intent.kind == QuestionKind(atteso.kind)


def test_rust_param_interroga_il_crate(monkeypatch):
    """Path runtime reale: l'engine passa `backend="rust"` come PARAMETRO (non
    via costante di modulo). Prova con una spia che il wheel nativo
    `tiq_intent.score` sia davvero interrogato — non basta la parità dell'output,
    che passerebbe anche col fallback Python (Slice 7, difetto attivazione)."""
    tiq_intent = pytest.importorskip("tiq_intent")
    if not hasattr(tiq_intent, "score"):
        pytest.skip("modulo tiq_intent presente senza estensione nativa score")

    # Costante di modulo ferma a "model" (com'e' in prod): la scelta del crate
    # deve venire dal parametro, altrimenti il difetto non e' catturato.
    monkeypatch.setattr(intent_mod, "_INTENT_BACKEND", "model")

    chiamate = {"n": 0}
    originale = tiq_intent.score

    def spia(message):
        chiamate["n"] += 1
        return originale(message)

    monkeypatch.setattr(tiq_intent, "score", spia)

    msg = "orari ufficio anagrafe"
    intent = asyncio.run(
        extract_intent(message=msg, provider=_ProviderCheEsplode(), backend="rust")
    )
    assert chiamate["n"] >= 1, "il crate nativo non e' stato interrogato"
    atteso = score_intent(msg)
    assert intent.topic == Topic(atteso.topic)
    assert intent.kind == QuestionKind(atteso.kind)


def test_backend_python_non_chiama_il_crate(monkeypatch):
    """Col backend deterministico Python ("scorer") il crate non deve mai essere
    interrogato, anche quando il wheel e' installato."""
    monkeypatch.setattr(intent_mod, "_INTENT_BACKEND", "model")

    tiq_intent = pytest.importorskip("tiq_intent")
    if hasattr(tiq_intent, "score"):

        def esplode(message):
            raise AssertionError("backend scorer non deve interrogare il crate Rust")

        monkeypatch.setattr(tiq_intent, "score", esplode)

    msg = "orari ufficio anagrafe"
    intent = asyncio.run(
        extract_intent(message=msg, provider=_ProviderCheEsplode(), backend="scorer")
    )
    atteso = score_intent(msg)
    assert intent.topic == Topic(atteso.topic)
    assert intent.kind == QuestionKind(atteso.kind)


def test_rust_assente_ripiega_su_python(monkeypatch):
    """Immagine senza wheel (stage base/runtime di prod): `import tiq_intent`
    alza ImportError, il backend "rust" ripiega sullo scorer Python senza
    crash, con esito identico (I-2 fail-safe)."""
    monkeypatch.setattr(intent_mod, "_INTENT_BACKEND", "model")
    # sys.modules[...] = None fa alzare ImportError all'`import tiq_intent`
    # dentro _score_livello_a, simulando l'assenza del wheel nativo.
    monkeypatch.setitem(sys.modules, "tiq_intent", None)

    msg = "voglio pagare la tari"
    intent = asyncio.run(
        extract_intent(message=msg, provider=_ProviderCheEsplode(), backend="rust")
    )
    atteso = score_intent(msg)
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
