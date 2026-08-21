"""Step 1 (T0 — codice ISTAT): a read-only contract that validates the
municipality frame before anyone reads it.

Today ten call sites open ``data/comuni-istat.json`` and each one fails in its
own way when the frame is absent or malformed: ``sonda_live`` degrades to a
mute ``{}``, ``registro_cli`` raises a talking ``SystemExit``, ``dati_cli``
silently drops the row from a report, and ``censimento`` — with no guard at
all — crashes with a raw ``FileNotFoundError``. Four contracts for one file.

This module gives that single file a single verdict. It does **not** touch the
runtime yet: nothing here is wired into a reader, and nothing writes the frame.
It only reads a frame (or a path, or a raw string) and returns a
:class:`FrameValidationReport` that separates two very different failures:

* an **identity** failure — a missing/invalid ``codice_istat``, a duplicate
  code, a missing required column, unparseable JSON — orphans persisted data
  keyed on that code. It is blocking: outcome ``INVALID``.
* an **anomaly** — a missing optional field, a shared ``codice_ipa``, a new
  additive column, a large drop against a previous count — is suspicious but
  not corrupting. It wants human eyes, not a hard stop: outcome
  ``REVIEW_REQUIRED``.

The distinction is the whole point: a batch job must abort on ``INVALID`` and
may proceed-with-warning on ``REVIEW_REQUIRED``. Wiring that decision into the
actual readers is Step 3, not this step.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

#: A valid ISTAT municipal code: exactly six digits, zero-padded. The frame
#: stores them as strings ("001001") precisely so the leading zero survives —
#: an int would turn Agliè's 001001 into 1001 and orphan every artifact keyed
#: on the string form.
_CODICE_ISTAT = re.compile(r"^\d{6}$")

#: The columns the frame is contractually expected to carry. ``sito`` and
#: ``codice_ipa`` are optional (F-7: 29 comuni have no site, 8 have no IPA
#: code), the other four are the identity of a municipality and must exist.
_REQUIRED_COLUMNS = frozenset({"codice_istat", "nome", "provincia", "regione"})
_OPTIONAL_COLUMNS = frozenset({"sito", "codice_ipa"})
_KNOWN_COLUMNS = _REQUIRED_COLUMNS | _OPTIONAL_COLUMNS


class FrameOutcome(str, Enum):
    """The three verdicts a frame can receive, worst to best when combined."""

    #: The frame cannot be trusted as a join key source. A batch must abort.
    INVALID = "invalid"
    #: The frame is usable but something changed that a human should confirm.
    REVIEW_REQUIRED = "review_required"
    #: The frame is well-formed and consistent with the baseline (if given).
    VALID = "valid"


class IssueSeverity(str, Enum):
    """Whether an issue blocks (identity) or merely warns (anomaly)."""

    BLOCKING = "blocking"
    ANOMALY = "anomaly"


@dataclass(frozen=True)
class FrameIssue:
    """One problem found in the frame, attributed to a row where possible."""

    severity: IssueSeverity
    code: str
    detail: str
    #: The ``codice_istat`` the issue attaches to, or ``None`` for
    #: frame-level problems (unparseable JSON, count drop, absent file).
    codice: str | None = None
    #: The row index, when the row has no usable code to name it by.
    riga: int | None = None


@dataclass(frozen=True)
class FrameValidationReport:
    """The verdict on one frame, plus every issue that justified it."""

    outcome: FrameOutcome
    issues: tuple[FrameIssue, ...] = ()
    #: Rows that parsed as objects, whether or not they were valid.
    row_count: int = 0
    #: Distinct valid ``codice_istat`` values seen (the usable join keys).
    valid_codes: int = 0

    @property
    def blocking(self) -> tuple[FrameIssue, ...]:
        return tuple(i for i in self.issues if i.severity is IssueSeverity.BLOCKING)

    @property
    def anomalies(self) -> tuple[FrameIssue, ...]:
        return tuple(i for i in self.issues if i.severity is IssueSeverity.ANOMALY)


@dataclass(frozen=True)
class FrameBaseline:
    """What a previous good frame looked like, for drift comparison.

    A raw minimum count is not enough: 7.896 is fine today and catastrophic if
    ISTAT ever publishes 8.500 comuni. The honest question is *did the count
    move more than it should have relative to last time*, so the baseline
    carries the previous count and the tolerated drop ratio travels with it.
    """

    #: How many valid codes the last accepted frame carried.
    valid_codes: int
    #: Fraction of rows allowed to disappear before it becomes an anomaly.
    #: 0.02 means: lose more than 2% of the comuni and a human looks.
    max_drop_ratio: float = 0.02

    def drop_is_massive(self, current_valid_codes: int) -> bool:
        floor = self.valid_codes * (1.0 - self.max_drop_ratio)
        return current_valid_codes < floor


class FrameValidator:
    """Read-only validator for the municipality frame.

    Three entry points, narrowing from least to most trusted input:

    * :meth:`validate_path` — a path that may not exist (models the absent-file
      fail-mode every reader handles differently today);
    * :meth:`validate_text` — a raw string that may not be valid JSON (models
      the truncated/corrupted frame);
    * :meth:`validate` — an already-parsed object (the common case once the
      bytes are known good).

    None of them writes anything.
    """

    def validate_path(
        self, path: str | Path, *, baseline: FrameBaseline | None = None
    ) -> FrameValidationReport:
        p = Path(path)
        if not p.exists():
            return FrameValidationReport(
                outcome=FrameOutcome.INVALID,
                issues=(
                    FrameIssue(
                        severity=IssueSeverity.BLOCKING,
                        code="frame_absent",
                        detail=f"frame non trovato: {p}",
                    ),
                ),
            )
        return self.validate_text(p.read_text("utf-8"), baseline=baseline)

    def validate_text(
        self, text: str, *, baseline: FrameBaseline | None = None
    ) -> FrameValidationReport:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return FrameValidationReport(
                outcome=FrameOutcome.INVALID,
                issues=(
                    FrameIssue(
                        severity=IssueSeverity.BLOCKING,
                        code="frame_unparseable",
                        detail=f"JSON non decodificabile: {exc}",
                    ),
                ),
            )
        return self.validate(data, baseline=baseline)

    def validate(
        self, data: Any, *, baseline: FrameBaseline | None = None
    ) -> FrameValidationReport:
        if not isinstance(data, list):
            return FrameValidationReport(
                outcome=FrameOutcome.INVALID,
                issues=(
                    FrameIssue(
                        severity=IssueSeverity.BLOCKING,
                        code="frame_not_a_list",
                        detail=f"il frame deve essere una lista, trovato {type(data).__name__}",
                    ),
                ),
            )

        issues: list[FrameIssue] = []
        row_count = 0
        seen_codes: dict[str, int] = {}
        ipa_owners: dict[str, list[str]] = {}

        for index, riga in enumerate(data):
            if not isinstance(riga, dict):
                issues.append(
                    FrameIssue(
                        severity=IssueSeverity.BLOCKING,
                        code="row_not_object",
                        detail=f"riga {index} non è un oggetto: {type(riga).__name__}",
                        riga=index,
                    )
                )
                continue
            row_count += 1
            self._check_row(index, riga, seen_codes, ipa_owners, issues)

        self._check_shared_ipa(ipa_owners, issues)

        valid_codes = sum(1 for c, n in seen_codes.items() if n == 1)
        if baseline is not None and baseline.drop_is_massive(valid_codes):
            issues.append(
                FrameIssue(
                    severity=IssueSeverity.ANOMALY,
                    code="count_drop",
                    detail=(
                        f"codici validi {valid_codes} sotto la soglia "
                        f"{baseline.valid_codes} × (1 − {baseline.max_drop_ratio})"
                    ),
                )
            )

        outcome = self._verdict(issues)
        return FrameValidationReport(
            outcome=outcome,
            issues=tuple(issues),
            row_count=row_count,
            valid_codes=valid_codes,
        )

    # -- row-level checks ---------------------------------------------------

    def _check_row(
        self,
        index: int,
        riga: dict,
        seen_codes: dict[str, int],
        ipa_owners: dict[str, list[str]],
        issues: list[FrameIssue],
    ) -> None:
        keys = set(riga)

        missing = _REQUIRED_COLUMNS - keys
        for column in sorted(missing):
            issues.append(
                FrameIssue(
                    severity=IssueSeverity.BLOCKING,
                    code="missing_column",
                    detail=f"riga {index}: colonna richiesta assente «{column}»",
                    riga=index,
                )
            )

        # An additive column is not corruption, but the frame's shape just
        # changed under us: someone should confirm the generator meant it.
        for column in sorted(keys - _KNOWN_COLUMNS):
            issues.append(
                FrameIssue(
                    severity=IssueSeverity.ANOMALY,
                    code="unknown_column",
                    detail=f"riga {index}: colonna non prevista «{column}»",
                    riga=index,
                )
            )

        codice = riga.get("codice_istat")
        if not isinstance(codice, str) or not _CODICE_ISTAT.match(codice):
            issues.append(
                FrameIssue(
                    severity=IssueSeverity.BLOCKING,
                    code="invalid_codice_istat",
                    detail=f"riga {index}: codice_istat non valido {codice!r}",
                    codice=codice if isinstance(codice, str) else None,
                    riga=index,
                )
            )
        else:
            seen_codes[codice] = seen_codes.get(codice, 0) + 1
            if seen_codes[codice] == 2:
                issues.append(
                    FrameIssue(
                        severity=IssueSeverity.BLOCKING,
                        code="duplicate_codice_istat",
                        detail=f"codice_istat duplicato {codice!r}",
                        codice=codice,
                    )
                )

        for column in ("nome", "provincia", "regione"):
            value = riga.get(column)
            if column in riga and (not isinstance(value, str) or not value.strip()):
                issues.append(
                    FrameIssue(
                        severity=IssueSeverity.BLOCKING,
                        code="empty_required_field",
                        detail=f"riga {index}: «{column}» vuoto o non testuale",
                        codice=codice if isinstance(codice, str) else None,
                        riga=index,
                    )
                )

        # Optional data. A bare hostname ("www.comune.x.it") is the frame's
        # normal form, NOT an error — the only thing worth noting is a present
        # value that is not a string. Absence is tolerated in silence here
        # because it is already known and counted (F-7).
        sito = riga.get("sito")
        if "sito" in riga and sito is not None and not isinstance(sito, str):
            issues.append(
                FrameIssue(
                    severity=IssueSeverity.ANOMALY,
                    code="sito_not_string",
                    detail=f"riga {index}: sito non testuale {sito!r}",
                    codice=codice if isinstance(codice, str) else None,
                    riga=index,
                )
            )

        ipa = riga.get("codice_ipa")
        if isinstance(ipa, str) and ipa.strip() and isinstance(codice, str):
            ipa_owners.setdefault(ipa, []).append(codice)

    def _check_shared_ipa(
        self, ipa_owners: dict[str, list[str]], issues: list[FrameIssue]
    ) -> None:
        for ipa, owners in ipa_owners.items():
            if len(owners) > 1:
                issues.append(
                    FrameIssue(
                        severity=IssueSeverity.ANOMALY,
                        code="shared_codice_ipa",
                        detail=f"codice_ipa {ipa!r} condiviso da {sorted(owners)}",
                    )
                )

    @staticmethod
    def _verdict(issues: list[FrameIssue]) -> FrameOutcome:
        if any(i.severity is IssueSeverity.BLOCKING for i in issues):
            return FrameOutcome.INVALID
        if issues:
            return FrameOutcome.REVIEW_REQUIRED
        return FrameOutcome.VALID
