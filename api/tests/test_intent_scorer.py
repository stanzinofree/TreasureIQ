"""Valida l'oracolo Python `score_intent` contro i casi golden condivisi.

Gli stessi `tiq_intent/cases.json` valideranno il crate Rust: se questo test
passa e il crate produce lo stesso output, l'implementazione Rust e' corretta
per costruzione (stesso oracolo).
"""
import json
from pathlib import Path

import pytest

from treasureiq.chat.intent_scorer import score_intent

_CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "tiq_intent" / "cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize("caso", _CASES, ids=lambda c: c["msg"][:40] or "<vuoto>")
def test_scorer_golden(caso: dict) -> None:
    res = score_intent(caso["msg"])
    atteso = caso["topic"] if caso["topic"] is not None else "sconosciuto"
    assert res.topic == atteso, f"topic: {caso['msg']!r} -> {res.topic} (atteso {atteso})"
    assert res.kind == caso["kind"], f"kind: {caso['msg']!r} -> {res.kind}"


def test_topic_scelto_e_sempre_un_topic_reale() -> None:
    """Lo scorer non deve mai inventare un topic fuori dall'enum Topic."""
    from treasureiq.chat.intent import Topic

    validi = {t.value for t in Topic}
    for caso in _CASES:
        assert score_intent(caso["msg"]).topic in validi


def test_deterministico() -> None:
    m = "non riesco a pagare le bollette della luce"
    assert score_intent(m) == score_intent(m)
