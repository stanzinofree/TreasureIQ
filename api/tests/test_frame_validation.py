"""Step 1 (T0 — codice ISTAT): fixtures + contract for the read-only
``FrameValidator``. No network, no touching the real frame, fully deterministic.

The frame is the join key source for every persisted artifact keyed on
``codice_istat``; these tests pin the boundary between a *blocking* identity
failure (``INVALID``) and a *review* anomaly (``REVIEW_REQUIRED``).
"""

from __future__ import annotations

import json

from treasureiq.frame_validation import (
    FrameBaseline,
    FrameIssue,
    FrameOutcome,
    FrameValidationReport,
    FrameValidator,
    IssueSeverity,
)


def _row(
    codice: str,
    nome: str,
    provincia: str = "RM",
    regione: str = "Lazio",
    sito: str | None = "www.comune.esempio.it",
    codice_ipa: str | None = "C_X001",
) -> dict:
    row: dict = {
        "codice_istat": codice,
        "nome": nome,
        "provincia": provincia,
        "regione": regione,
    }
    if sito is not None:
        row["sito"] = sito
    if codice_ipa is not None:
        row["codice_ipa"] = codice_ipa
    return row


def _good_frame() -> list[dict]:
    # A faithful-shaped, tiny frame: distinct 6-digit codes, distinct IPA.
    return [
        _row("001001", "Agliè", "TO", "Piemonte", "www.comune.aglie.to.it", "C_A074"),
        _row("058003", "Albano Laziale", "RM", "Lazio", "www.comunedialbanolaziale.it", "C_A132"),
        _row("058079", "Pomezia", "RM", "Lazio", "www.comune.pomezia.rm.it", "C_G811"),
    ]


def _codes(issues: tuple[FrameIssue, ...]) -> set[str]:
    return {i.code for i in issues}


# -- happy path -------------------------------------------------------------


def test_well_formed_frame_is_valid() -> None:
    report = FrameValidator().validate(_good_frame())
    assert report.outcome is FrameOutcome.VALID
    assert report.issues == ()
    assert report.row_count == 3
    assert report.valid_codes == 3


def test_schemeless_site_is_accepted_not_flagged() -> None:
    # The frame stores bare hostnames by design. A site "without scheme" is the
    # NORMAL case and must never be treated as an anomaly.
    frame = [_row("058003", "Albano Laziale", sito="www.comunedialbanolaziale.it")]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.VALID
    assert "sito_not_string" not in _codes(report.issues)


# -- blocking: identity failures → INVALID ----------------------------------


def test_absent_file_is_invalid(tmp_path) -> None:
    # Models the fail-mode every reader handles differently today: here it is
    # one blocking verdict instead of {} / SystemExit / raw FileNotFoundError.
    missing = tmp_path / "comuni-istat.json"
    report = FrameValidator().validate_path(missing)
    assert report.outcome is FrameOutcome.INVALID
    assert "frame_absent" in _codes(report.issues)


def test_truncated_json_is_invalid(tmp_path) -> None:
    # "corruzione / JSON troncato": bytes cut off mid-object.
    text = json.dumps(_good_frame())[: len(json.dumps(_good_frame())) // 2]
    report = FrameValidator().validate_text(text)
    assert report.outcome is FrameOutcome.INVALID
    assert "frame_unparseable" in _codes(report.issues)


def test_frame_not_a_list_is_invalid() -> None:
    report = FrameValidator().validate({"001001": {"nome": "Agliè"}})
    assert report.outcome is FrameOutcome.INVALID
    assert "frame_not_a_list" in _codes(report.issues)


def test_invalid_codice_istat_is_blocking() -> None:
    # "codice invalido": not six digits. Would orphan every keyed artifact.
    frame = [_row("58003", "Albano Laziale"), _row("001001", "Agliè")]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.INVALID
    codice_issue = next(i for i in report.issues if i.code == "invalid_codice_istat")
    assert codice_issue.severity is IssueSeverity.BLOCKING


def test_non_string_codice_istat_is_blocking() -> None:
    # An int 1001 loses the leading zeros → different key. Must be caught.
    frame = [{"codice_istat": 1001, "nome": "Agliè", "provincia": "TO", "regione": "Piemonte"}]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.INVALID
    assert "invalid_codice_istat" in _codes(report.issues)


def test_duplicate_codice_istat_is_blocking() -> None:
    # "duplicati": two rows claim the same join key.
    frame = _good_frame() + [_row("058003", "Albano Laziale (dup)", codice_ipa="C_ZZZ9")]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.INVALID
    dup = next(i for i in report.issues if i.code == "duplicate_codice_istat")
    assert dup.codice == "058003"


def test_missing_required_column_is_blocking() -> None:
    # "schema cambiato" (subtractive): the identity column vanished.
    frame = [{"codice_istat": "001001", "provincia": "TO", "regione": "Piemonte"}]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.INVALID
    missing = next(i for i in report.issues if i.code == "missing_column")
    assert "nome" in missing.detail


def test_row_not_object_is_blocking() -> None:
    report = FrameValidator().validate(_good_frame() + ["001001"])
    assert report.outcome is FrameOutcome.INVALID
    assert "row_not_object" in _codes(report.issues)


def test_empty_required_field_is_blocking() -> None:
    frame = [_row("001001", "   ")]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.INVALID
    assert "empty_required_field" in _codes(report.issues)


# -- review: anomalies → REVIEW_REQUIRED ------------------------------------


def test_additive_schema_change_is_review_not_blocking() -> None:
    # "schema cambiato" (additive): a new column appears. Not corruption, but
    # the shape moved under us — a human confirms the generator meant it.
    frame = _good_frame()
    frame[0] = {**frame[0], "popolazione": 2600}
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.REVIEW_REQUIRED
    assert "unknown_column" in _codes(report.issues)
    assert report.blocking == ()


def test_shared_codice_ipa_is_review() -> None:
    frame = [
        _row("001001", "Agliè", "TO", "Piemonte", codice_ipa="C_SHARE"),
        _row("058003", "Albano Laziale", codice_ipa="C_SHARE"),
    ]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.REVIEW_REQUIRED
    shared = next(i for i in report.issues if i.code == "shared_codice_ipa")
    assert shared.severity is IssueSeverity.ANOMALY


def test_missing_optional_fields_stay_valid() -> None:
    # No sito, no codice_ipa: known and counted (F-7), not an anomaly.
    frame = [_row("001001", "Agliè", sito=None, codice_ipa=None)]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.VALID


# -- review: count drop is compared to a baseline, not an absolute floor ----


def test_massive_count_drop_against_baseline_is_review() -> None:
    # "calo massivo": baseline had 7896 valid codes; a frame of 3 is a cliff.
    baseline = FrameBaseline(valid_codes=7896, max_drop_ratio=0.02)
    report = FrameValidator().validate(_good_frame(), baseline=baseline)
    assert report.outcome is FrameOutcome.REVIEW_REQUIRED
    assert "count_drop" in _codes(report.issues)


def test_count_within_tolerance_stays_valid() -> None:
    # 3 valid codes vs a baseline of 3 → no drop, still VALID.
    baseline = FrameBaseline(valid_codes=3, max_drop_ratio=0.02)
    report = FrameValidator().validate(_good_frame(), baseline=baseline)
    assert report.outcome is FrameOutcome.VALID


def test_count_drop_is_relative_not_absolute() -> None:
    # A raw minimum would be wrong: the SAME count of 3 is fine against a
    # baseline of 3 and an anomaly against a baseline of 7896. The policy is
    # relative to the previous frame, which is the whole design point.
    v = FrameValidator()
    assert v.validate(_good_frame(), baseline=FrameBaseline(3)).outcome is FrameOutcome.VALID
    assert (
        v.validate(_good_frame(), baseline=FrameBaseline(7896)).outcome
        is FrameOutcome.REVIEW_REQUIRED
    )


# -- policy separation: blocking always wins over anomaly -------------------


def test_blocking_and_anomaly_together_resolve_to_invalid() -> None:
    # A frame with BOTH a duplicate (blocking) and a shared IPA (anomaly)
    # must resolve to INVALID: identity failure dominates.
    frame = [
        _row("001001", "Agliè", "TO", "Piemonte", codice_ipa="C_SHARE"),
        _row("001001", "Agliè bis", "TO", "Piemonte", codice_ipa="C_SHARE"),
    ]
    report = FrameValidator().validate(frame)
    assert report.outcome is FrameOutcome.INVALID
    assert len(report.blocking) >= 1
    assert len(report.anomalies) >= 1


def test_report_is_a_frozen_dataclass() -> None:
    report = FrameValidator().validate(_good_frame())
    assert isinstance(report, FrameValidationReport)
    try:
        report.outcome = FrameOutcome.INVALID  # type: ignore[misc]
    except Exception as exc:  # frozen → FrozenInstanceError
        assert "cannot assign" in str(exc) or "frozen" in type(exc).__name__.lower()
    else:  # pragma: no cover
        raise AssertionError("report should be immutable")
