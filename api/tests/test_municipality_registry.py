"""Step 2 (T0 — codice ISTAT): tests for the typed, read-only
``MunicipalityRegistry`` / ``SourceFrame``.

Two things are pinned here:

* **behaviour parity** with the current ``sonda_live`` lookups, checked on the
  *same* small frame injected into both — so Step 3 can make ``sonda_live``
  delegate to the registry without changing what any of its 41+ callers see;
* the Step 2 **guardrails**: typed model refuses invalid identity, INVALID
  frame is refused at build, I/O failure is distinct from invalid content,
  REVIEW warnings propagate, and the frame is read once per configuration.

No network. No writing the real frame.
"""

from __future__ import annotations

import json

import pytest

from treasureiq import sonda_live
from treasureiq.frame_validation import FrameBaseline
from treasureiq.municipality_registry import (
    FrameInvalidError,
    FrameIOError,
    MunicipalityRecord,
    MunicipalityRegistry,
    SourceFrame,
    get_registry,
    reset_registry_cache,
)


def _row(codice, nome, provincia="RM", regione="Lazio", sito="www.x.it", codice_ipa="C_X001"):
    return {
        "codice_istat": codice,
        "nome": nome,
        "provincia": provincia,
        "regione": regione,
        "sito": sito,
        "codice_ipa": codice_ipa,
    }


def _frame():
    # Crafted to exercise every lookup branch:
    #  - two "Castro" rows → homonym, resolve must return None;
    #  - "Marino" with no "San Marino" present → toponym guard;
    #  - "Monterotondo" → compact-key match for "monte rotondo";
    #  - "Reggio nell'Emilia" → empty-word compaction ("reggio emilia");
    #  - a couple ordinary rows for search ordering.
    return [
        _row("058057", "Marino", "RM", "Lazio", "www.comune.marino.rm.it", "C_E958"),
        _row("072019", "Castro", "BA", "Puglia", "www.comune.castro.ba.it", "C_C337"),
        _row("016078", "Castro", "BG", "Lombardia", "www.comune.castro.bg.it", "C_C338"),
        _row("058061", "Monterotondo", "RM", "Lazio", "www.comune.monterotondo.rm.it", "C_F611"),
        _row("035033", "Reggio nell'Emilia", "RE", "Emilia-Romagna", "www.comune.re.it", "C_H223"),
        _row("058091", "Roma", "RM", "Lazio", "www.comune.roma.it", "C_H501"),
    ]


@pytest.fixture
def sonda_su_frame(tmp_path, monkeypatch):
    """Point sonda_live at the same small frame so parity is a fair comparison."""
    p = tmp_path / "comuni-istat.json"
    p.write_text(json.dumps(_frame(), ensure_ascii=False), "utf-8")
    monkeypatch.setattr(sonda_live, "COMUNI_ISTAT_PATH", p)
    reset_registry_cache()
    sonda_live._warned_frame_io = False
    sonda_live._warned_frame_invalid = False
    yield p
    reset_registry_cache()


def _sf() -> SourceFrame:
    return SourceFrame.from_validated(_frame())


# -- parity with sonda_live -------------------------------------------------


def test_parity_comune_per_codice(sonda_su_frame) -> None:
    reg = MunicipalityRegistry.from_path(sonda_su_frame)
    for codice in ("058057", "072019", "999999", None):
        mine = reg.comune_per_codice(codice)
        theirs = sonda_live.comune_per_codice(codice)
        assert (mine is None) == (theirs is None)
        if mine is not None:
            assert mine.codice_istat == theirs.codice_istat
            assert mine.nome == theirs.nome


def test_parity_risolvi_homonym_returns_none(sonda_su_frame) -> None:
    reg = MunicipalityRegistry.from_path(sonda_su_frame)
    # "Castro" is a homonym → both must refuse to guess.
    assert reg.risolvi_comune("vivo a Castro") is None
    assert sonda_live.risolvi_comune("vivo a Castro") is None


def test_parity_risolvi_toponym_guard(sonda_su_frame) -> None:
    reg = MunicipalityRegistry.from_path(sonda_su_frame)
    # "San Marino" must NOT resolve to Marino (RM) in either.
    assert reg.risolvi_comune("vivo a San Marino") is None
    assert sonda_live.risolvi_comune("vivo a San Marino") is None
    # Plain "Marino" resolves in both.
    assert reg.risolvi_comune("abito a Marino").codice_istat == "058057"
    assert sonda_live.risolvi_comune("abito a Marino").codice_istat == "058057"


def test_parity_risolvi_compact_key(sonda_su_frame) -> None:
    reg = MunicipalityRegistry.from_path(sonda_su_frame)
    # "monte rotondo" (spaced) must fall on "Monterotondo".
    mine = reg.risolvi_comune("sto a monte rotondo")
    theirs = sonda_live.risolvi_comune("sto a monte rotondo")
    assert mine is not None and theirs is not None
    assert mine.codice_istat == theirs.codice_istat == "058061"


def test_parity_cerca_order_and_membership(sonda_su_frame) -> None:
    reg = MunicipalityRegistry.from_path(sonda_su_frame)
    for query in ("Castro", "comune di Roma", "Reggio Emilia", "ro", "xyz"):
        mine = [c.codice_istat for c in reg.cerca_comuni(query)]
        theirs = [c.codice_istat for c in sonda_live.cerca_comuni(query)]
        assert mine == theirs, f"divergenza su {query!r}: {mine} vs {theirs}"


# -- typed model + build guardrails ----------------------------------------


def test_record_is_superset_of_comune_noto() -> None:
    # Every ComuneNoto field must exist on MunicipalityRecord (signature compat).
    noto_fields = set(sonda_live.ComuneNoto.model_fields)
    record_fields = set(MunicipalityRecord.model_fields)
    assert noto_fields <= record_fields
    assert "codice_ipa" in record_fields  # the added consolidation


def test_record_refuses_non_six_digit_codice() -> None:
    with pytest.raises(ValueError):
        MunicipalityRecord(codice_istat="58057", nome="Marino", provincia="RM", regione="Lazio")


def test_invalid_frame_refused_at_build() -> None:
    bad = _frame() + [_row("058057", "Marino dup")]  # duplicate → INVALID
    with pytest.raises(FrameInvalidError) as exc:
        SourceFrame.from_validated(bad)
    assert "duplicate_codice_istat" in str(exc.value)


def test_io_error_distinct_from_invalid(tmp_path) -> None:
    # Missing file → FrameIOError (operational).
    with pytest.raises(FrameIOError):
        SourceFrame.from_path(tmp_path / "nope.json")
    # Present but truncated → FrameInvalidError (integrity), NOT FrameIOError.
    truncated = tmp_path / "trunc.json"
    truncated.write_text(json.dumps(_frame())[:40], "utf-8")
    with pytest.raises(FrameInvalidError):
        SourceFrame.from_path(truncated)


def test_review_required_frame_builds_and_propagates_warning() -> None:
    baseline = FrameBaseline(valid_codes=7896, max_drop_ratio=0.02)
    frame = SourceFrame.from_validated(_frame(), baseline=baseline)
    # Massive count drop is an anomaly, not a block: it builds, with a warning.
    assert frame.warnings
    assert any(i.code == "count_drop" for i in frame.warnings)


def test_ipa_map_only_where_present() -> None:
    frame = _frame()
    frame[0] = {**frame[0], "codice_ipa": None}
    sf = SourceFrame.from_validated(frame)
    m = sf.ipa_map()
    assert "058057" not in m
    assert m["072019"] == "C_C337"


# -- load-once caching ------------------------------------------------------


def test_get_registry_loads_once_per_config(sonda_su_frame) -> None:
    reset_registry_cache()
    a = get_registry(sonda_su_frame)
    b = get_registry(sonda_su_frame)
    assert a is b  # same instance → frame read once
    # A different baseline is a genuinely different configuration.
    c = get_registry(sonda_su_frame, baseline=FrameBaseline(6))
    assert c is not a
    reset_registry_cache()


def test_no_write_to_frame(sonda_su_frame) -> None:
    before = sonda_su_frame.read_bytes()
    MunicipalityRegistry.from_path(sonda_su_frame).cerca_comuni("Roma")
    assert sonda_su_frame.read_bytes() == before


def test_sonda_wrappers_keep_public_type_and_one_coherent_registry(monkeypatch, tmp_path) -> None:
    frame_a = tmp_path / "a.json"
    frame_b = tmp_path / "b.json"
    frame_a.write_text(json.dumps([_row("001001", "Agliè")]), encoding="utf-8")
    frame_b.write_text(json.dumps([_row("058003", "Albano Laziale")]), encoding="utf-8")

    reset_registry_cache()
    monkeypatch.setattr(sonda_live, "COMUNI_ISTAT_PATH", frame_a)
    aglie = sonda_live.comune_per_codice("001001")
    assert aglie is not None
    assert isinstance(aglie, sonda_live.ComuneNoto)
    assert "codice_ipa" not in aglie.model_dump()

    # Changing the path without resetting must produce one coherent registry,
    # never a mixture where one public function serves A and another serves B.
    monkeypatch.setattr(sonda_live, "COMUNI_ISTAT_PATH", frame_b)
    albano = sonda_live.comune_per_codice("058003")
    assert albano is not None and albano.nome == "Albano Laziale"
    assert sonda_live.comune_per_codice("001001") is None
    assert [c.codice_istat for c in sonda_live.cerca_comuni("Albano")] == ["058003"]
