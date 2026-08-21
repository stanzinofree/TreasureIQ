"""Step 2 (T0 — codice ISTAT): a typed, read-only registry over a *validated*
municipality frame.

Today ten call sites read ``data/comuni-istat.json`` directly; eight of them
parse the raw dict and never validate a row, and the lookup/search logic lives
in ``sonda_live`` where it is entangled with everything else. This module is the
single place that:

1. loads the frame **once** per (path, baseline) configuration;
2. refuses to build from data the :class:`FrameValidator` calls ``INVALID``;
3. exposes typed :class:`MunicipalityRecord` rows (a superset of
   ``sonda_live.ComuneNoto`` plus ``codice_ipa``);
4. offers the four public lookups the runtime already depends on —
   ``comune_per_codice``, ``risolvi_comune``, ``cerca_comuni`` and the IPA map —
   with the *same* behaviour, so Step 3 can make ``sonda_live`` delegate here
   without changing any of its 41+ callers.

It is **not wired into the runtime yet**: nothing here is imported by a reader,
and nothing writes the frame. This step only builds the contract and proves
parity with the current ``sonda_live`` semantics.

Two failure modes are kept distinct on purpose, because the callers must react
differently: an :class:`FrameIOError` (the file is missing or unreadable) is an
operational problem, while an :class:`FrameInvalidError` (the bytes parsed but
the content is corrupt as a join-key source) is a data-integrity problem.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from treasureiq.frame_validation import (
    FrameBaseline,
    FrameIssue,
    FrameOutcome,
    FrameValidationReport,
    FrameValidator,
)

logger = logging.getLogger(__name__)

_CODICE_ISTAT = re.compile(r"^\d{6}$")

# Normalisation constants, replicated verbatim from ``sonda_live`` so the
# lookups here fall on exactly the same keys. Step 3 collapses the duplication
# by having ``sonda_live`` import these; until then, parity tests pin them.
_PREFISSI_TOPONIMO = frozenset(
    {"san", "santa", "santo", "sant", "borgo", "villa", "castel", "castello", "monte", "rocca"}
)
_PAROLE_VUOTE = frozenset(
    {"di", "del", "della", "dei", "delle", "in", "nel", "nell", "sul",
     "sull", "su", "a", "al", "alla", "d", "l", "e", "con"}
)
_PREFISSO_COMUNE = re.compile(
    r"^\s*(?:il\s+|la\s+)?(?:comune|citt[àa]|municipio|paese)\s+(?:di\s+|d['’]\s*)?",
    re.IGNORECASE,
)


class FrameIOError(OSError):
    """The frame file is missing or cannot be read. Operational, not corruption."""


class FrameInvalidError(ValueError):
    """The frame parsed but the validator rejected it as a join-key source."""

    def __init__(self, report: FrameValidationReport) -> None:
        self.report = report
        blocking = ", ".join(sorted({i.code for i in report.blocking})) or "?"
        super().__init__(f"frame INVALID: {blocking}")


def _norm(testo: str) -> str:
    """Chiave di confronto: senza accenti, senza punteggiatura, minuscola."""
    piatto = unicodedata.normalize("NFKD", testo)
    piatto = "".join(c for c in piatto if not unicodedata.combining(c))
    piatto = re.sub(r"[^\w\s]", " ", piatto.lower())
    return re.sub(r"\s+", " ", piatto).strip()


def _senza_parole_vuote(testo: str) -> str:
    """La forma in cui un cittadino scrive un nome ufficiale."""
    return " ".join(t for t in _norm(testo).split() if t not in _PAROLE_VUOTE)


class MunicipalityRecord(BaseModel):
    """A validated municipality row: ``ComuneNoto`` plus the IPA code.

    Frozen and self-guarding: even constructed directly it refuses a
    ``codice_istat`` that is not six digits, so a row cannot enter the registry
    having bypassed the validator's core identity rule.
    """

    model_config = ConfigDict(frozen=True)

    codice_istat: str
    nome: str
    provincia: str
    regione: str
    sito: str | None = None
    codice_ipa: str | None = None

    @field_validator("codice_istat")
    @classmethod
    def _codice_is_six_digits(cls, value: str) -> str:
        if not _CODICE_ISTAT.match(value):
            raise ValueError(f"codice_istat non valido: {value!r}")
        return value


class SourceFrame:
    """The validated frame in memory, indexed for the runtime lookups.

    Built only through :meth:`from_validated` / :meth:`from_path`, both of which
    run the :class:`FrameValidator` first and raise on ``INVALID``. A
    ``REVIEW_REQUIRED`` frame is accepted but its anomalies are kept in
    :attr:`report` and logged, so a warning is never silently swallowed.
    """

    def __init__(self, records: list[MunicipalityRecord], report: FrameValidationReport) -> None:
        self._records = records
        self.report = report
        # nome-normalizzato → record, esattamente come sonda_live._indice:
        # lista perché gli omonimi esistono (Castro, San Teodoro).
        self._per_nome: dict[str, list[MunicipalityRecord]] = {}
        self._per_codice: dict[str, MunicipalityRecord] = {}
        for record in records:
            self._per_codice.setdefault(record.codice_istat, record)
            for chiave in {_norm(record.nome), _senza_parole_vuote(record.nome)}:
                if chiave:
                    self._per_nome.setdefault(chiave, []).append(record)

    @classmethod
    def from_validated(
        cls, data: list[dict], *, baseline: FrameBaseline | None = None
    ) -> SourceFrame:
        report = FrameValidator().validate(data, baseline=baseline)
        if report.outcome is FrameOutcome.INVALID:
            raise FrameInvalidError(report)
        if report.outcome is FrameOutcome.REVIEW_REQUIRED:
            logger.warning(
                "frame in REVIEW_REQUIRED: %d anomalie — %s",
                len(report.anomalies),
                ", ".join(sorted({i.code for i in report.anomalies})),
            )
        records = [MunicipalityRecord.model_validate(riga) for riga in data]
        return cls(records, report)

    @classmethod
    def from_path(cls, path: str | Path, *, baseline: FrameBaseline | None = None) -> SourceFrame:
        p = Path(path)
        # I/O failure is kept distinct from content corruption: the file simply
        # not being there is an operational fault, not an invalid frame.
        if not p.exists():
            raise FrameIOError(f"frame non trovato: {p}")
        try:
            text = p.read_text("utf-8")
        except OSError as exc:  # unreadable, permission, etc.
            raise FrameIOError(f"frame illeggibile: {p}: {exc}") from exc

        report = FrameValidator().validate_text(text, baseline=baseline)
        if report.outcome is FrameOutcome.INVALID:
            raise FrameInvalidError(report)
        # Re-parse the validated text into records via from_validated's model
        # step; validate_text already confirmed it decodes to a list.
        import json

        data = json.loads(text)
        return cls.from_validated(data, baseline=baseline)

    # -- collection views ---------------------------------------------------

    @property
    def warnings(self) -> tuple[FrameIssue, ...]:
        return self.report.anomalies

    def tutti(self) -> list[MunicipalityRecord]:
        """Tutti i record, in ordine di codice: la base della ricerca testuale."""
        return sorted(self._per_codice.values(), key=lambda c: c.codice_istat)

    # -- the four runtime signatures ---------------------------------------

    def comune_per_codice(self, codice_istat: str | None) -> MunicipalityRecord | None:
        """Il comune per codice: la via che non può sbagliare (nessun omonimo)."""
        if not codice_istat:
            return None
        return self._per_codice.get(codice_istat)

    def risolvi_comune(self, hint: str | None) -> MunicipalityRecord | None:
        """Il comune nominato per intero nel testo, o ``None`` se ambiguo/assente.

        Replica ``sonda_live.risolvi_comune``: finestra di token, guardia sui
        prefissi-toponimo (``San Marino`` non è Marino), chiave compatta senza
        parole vuote. ``None`` sugli omonimi: non si indovina, si chiede.
        """
        if not hint:
            return None
        tokens = _norm(hint).split()
        if not tokens:
            return None

        # Finestre di token dalla più lunga alla più corta: il nome più
        # specifico presente nel testo vince.
        for lunghezza in range(min(len(tokens), 4), 0, -1):
            for inizio in range(0, len(tokens) - lunghezza + 1):
                # Guardia toponimo: "San Marino" non deve cadere su "Marino".
                if (
                    lunghezza == 1
                    and inizio > 0
                    and tokens[inizio - 1] in _PREFISSI_TOPONIMO
                ):
                    continue
                frase = " ".join(tokens[inizio : inizio + lunghezza])
                compatta = "".join(tokens[inizio : inizio + lunghezza])
                candidati = self._per_nome.get(frase) or self._per_nome.get(compatta)
                if candidati is None:
                    continue
                # Omonimi: più di un comune con questo nome → non indovinare.
                distinti = {c.codice_istat: c for c in candidati}
                if len(distinti) == 1:
                    return next(iter(distinti.values()))
                return None
        return None

    def cerca_comuni(self, query: str, *, limite: int = 8) -> list[MunicipalityRecord]:
        """I comuni che assomigliano a quanto scritto, per far scegliere.

        Replica ``sonda_live.cerca_comuni``: strip del prefisso «comune di»,
        rank esatto/inizio/contenuto, dedup per codice, ordine stabile.
        """
        ripulita = _PREFISSO_COMUNE.sub("", query.strip())
        chiave = _norm(ripulita)
        if len(chiave) < 2:
            return []
        compatta = _senza_parole_vuote(ripulita)

        trovati: dict[str, tuple[int, str, MunicipalityRecord]] = {}
        for record in self.tutti():
            nome = _norm(record.nome)
            senza = _senza_parole_vuote(record.nome)
            if chiave in (nome, senza) or compatta in (nome, senza):
                rango = 0
            elif nome.startswith(chiave) or senza.startswith(chiave):
                rango = 1
            elif chiave in nome or chiave in senza:
                rango = 2
            else:
                continue
            precedente = trovati.get(record.codice_istat)
            if precedente is None or rango < precedente[0]:
                trovati[record.codice_istat] = (rango, nome, record)

        ordinati = sorted(trovati.values(), key=lambda t: (t[0], t[1]))
        return [record for _, _, record in ordinati[:limite]]

    def ipa_map(self) -> dict[str, str]:
        """codice_istat → codice_ipa, solo dove IPA lo pubblica.

        La 4ª firma (oggi `registro._carica_comuni_ipa`), servita dallo stesso
        frame validato invece che da una seconda lettura del dict grezzo.
        """
        return {
            r.codice_istat: r.codice_ipa
            for r in self._records
            if r.codice_ipa
        }


class MunicipalityRegistry:
    """Load-once, read-only access to the municipality frame.

    One instance holds one loaded :class:`SourceFrame`. The module-level
    :func:`get_registry` caches instances per (path, baseline) so the frame is
    read once per configuration, not once per lookup.
    """

    def __init__(self, frame: SourceFrame) -> None:
        self._frame = frame

    @classmethod
    def from_path(
        cls, path: str | Path, *, baseline: FrameBaseline | None = None
    ) -> MunicipalityRegistry:
        return cls(SourceFrame.from_path(path, baseline=baseline))

    @property
    def frame(self) -> SourceFrame:
        return self._frame

    @property
    def warnings(self) -> tuple[FrameIssue, ...]:
        return self._frame.warnings

    def comune_per_codice(self, codice_istat: str | None) -> MunicipalityRecord | None:
        return self._frame.comune_per_codice(codice_istat)

    def risolvi_comune(self, hint: str | None) -> MunicipalityRecord | None:
        return self._frame.risolvi_comune(hint)

    def cerca_comuni(self, query: str, *, limite: int = 8) -> list[MunicipalityRecord]:
        return self._frame.cerca_comuni(query, limite=limite)

    def ipa_map(self) -> dict[str, str]:
        return self._frame.ipa_map()


#: Explicit per-configuration cache. Keyed on (resolved path, baseline) so a
#: different frame or a different drift baseline is a genuinely different load,
#: never a stale hit. Cleared with :func:`reset_registry_cache` in tests.
_CACHE: dict[tuple[str, tuple[int, float] | None], MunicipalityRegistry] = {}


def get_registry(
    path: str | Path, *, baseline: FrameBaseline | None = None
) -> MunicipalityRegistry:
    """The registry for ``path``, loaded once per (path, baseline)."""
    key = (
        str(Path(path).resolve()),
        (baseline.valid_codes, baseline.max_drop_ratio) if baseline else None,
    )
    cached = _CACHE.get(key)
    if cached is None:
        cached = MunicipalityRegistry.from_path(path, baseline=baseline)
        _CACHE[key] = cached
    return cached


def reset_registry_cache() -> None:
    """Drop every cached registry. For tests and controlled reloads only."""
    _CACHE.clear()
