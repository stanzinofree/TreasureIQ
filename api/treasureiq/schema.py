"""The Opportunity schema — TreasureIQ's core contribution.

This is deliberately more than an internal data model. It is proposed as a
minimal open specification that any Italian public administration could adopt
to make its benefits, grants and civic initiatives machine-readable.

The design constraint driving every field below: a machine must be able to
decide *whether a specific citizen is eligible* without a human reading prose.
Today that is impossible, because eligibility criteria live in PDF attachments
and free-text HTML. Every `Requirements` field here is a criterion we found
stated in natural language on a real comune website and had to extract.

Spec version is embedded in every record so consumers can migrate safely.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

SPEC_VERSION = "0.1.0"


class OpportunityKind(str, Enum):
    """What kind of thing the citizen is being offered.

    Split along the axis that matters to a citizen: am I *receiving* something
    (money, a service, a right) or am I being *asked to contribute* (volunteer,
    consultation, participatory budget)? TreasureIQ surfaces both, because the
    project's premise is that civic value flows in two directions.
    """

    # The citizen receives
    CONTRIBUTO_ECONOMICO = "contributo_economico"  # direct cash transfer
    VOUCHER = "voucher"  # earmarked spending credit
    AGEVOLAZIONE = "agevolazione"  # fee reduction / exemption
    SERVIZIO = "servizio"  # a service the citizen can request
    BANDO = "bando"  # competitive call requiring application

    # The citizen contributes
    VOLONTARIATO = "volontariato"
    CONSULTAZIONE = "consultazione"  # public consultation, participatory budget
    RACCOLTA_FONDI = "raccolta_fondi"

    ALTRO = "altro"


class TargetGroup(str, Enum):
    """Population segment an opportunity is aimed at.

    Kept coarse on purpose. Fine-grained targeting belongs in `Requirements`,
    which is machine-evaluable; this enum exists for browsing and filtering.
    """

    FAMIGLIE = "famiglie"
    MINORI = "minori"
    STUDENTI = "studenti"
    ANZIANI = "anziani"
    DISABILITA = "disabilita"
    DISOCCUPATI = "disoccupati"
    IMPRESE = "imprese"
    ASSOCIAZIONI = "associazioni"
    DONNE = "donne"
    STRANIERI = "stranieri"
    TUTTI = "tutti"


class EmploymentStatus(str, Enum):
    OCCUPATO = "occupato"
    DISOCCUPATO = "disoccupato"
    STUDENTE = "studente"
    PENSIONATO = "pensionato"
    INABILE = "inabile"


class Confidence(str, Enum):
    """How much to trust the structured fields on this record.

    This field is the honest core of the whole project. Most Italian comuni
    publish eligibility rules as prose, so TreasureIQ must *infer* structure.
    Pretending that inference is as reliable as a declared field would be a
    lie to the citizen, who may act on it.

    DECLARED  — the source published this field as structured, typed data.
    EXTRACTED — an LLM parsed it out of prose; plausible, not authoritative.
    INFERRED  — derived from weak signals (title keywords, category).

    The UI must visually distinguish DECLARED from the rest, and any non-
    DECLARED eligibility verdict must be shown as provisional with a link to
    the source. See `Opportunity.requires_human_verification`.
    """

    DECLARED = "declared"
    EXTRACTED = "extracted"
    INFERRED = "inferred"


class Livello(str, Enum):
    """Which administrative tier published this opportunity (D-20).

    Municipal connectors only ever produce `COMUNALE`; the hand-curated
    national/regional layer (`data/seed/nazionale_curated.json`) is the only
    producer of the other two. Defaulted so every seed written before this
    field existed keeps validating unchanged.
    """

    NAZIONALE = "nazionale"
    REGIONALE = "regionale"
    COMUNALE = "comunale"


class Money(BaseModel):
    """An amount, possibly a range, possibly open-ended."""

    min_eur: Decimal | None = Field(default=None, ge=0)
    max_eur: Decimal | None = Field(default=None, ge=0)
    note: str | None = Field(
        default=None,
        description="Free text for amounts that resist structuring, e.g. "
        "'50% della spesa sostenuta fino a capienza del fondo'.",
    )

    @model_validator(mode="after")
    def check_range(self) -> Money:
        if self.min_eur is not None and self.max_eur is not None:
            if self.min_eur > self.max_eur:
                raise ValueError("min_eur cannot exceed max_eur")
        return self


class Requirements(BaseModel):
    """Machine-evaluable eligibility criteria.

    Every field is optional and `None` means *not stated by the source*, which
    is emphatically NOT the same as *no constraint*. A missing `isee_max` on a
    benefit that obviously means-tests applicants is a data gap, and TreasureIQ
    reports it as such rather than silently treating the citizen as eligible.

    This distinction is the single most important semantic in the schema.
    """

    isee_max: Decimal | None = Field(
        default=None, ge=0, description="Maximum ISEE in EUR to qualify."
    )
    isee_min: Decimal | None = Field(default=None, ge=0)

    eta_min: int | None = Field(default=None, ge=0, le=130)
    eta_max: int | None = Field(default=None, ge=0, le=130)

    residenza_required: bool = Field(
        default=True,
        description="Whether residency in the issuing comune is required. "
        "Defaults True because municipal benefits almost always require it; "
        "regional and national sources should set this explicitly.",
    )
    residenza_comuni: list[str] = Field(
        default_factory=list,
        description="ISTAT codes of qualifying comuni. Empty means 'the "
        "issuing body's own territory'.",
    )

    nucleo_min: int | None = Field(
        default=None, ge=1, description="Minimum household size."
    )
    figli_minori_required: bool | None = None
    disabilita_required: bool | None = None

    employment_status: list[EmploymentStatus] = Field(
        default_factory=list,
        description="Qualifying employment statuses. Empty means unconstrained.",
    )

    other: list[str] = Field(
        default_factory=list,
        description="Criteria that could not be structured. Their presence is "
        "a signal that automated eligibility is incomplete for this record.",
    )

    source_typed: bool = Field(
        default=False,
        description="True when these values came from typed fields published "
        "by the source, rather than being recovered from prose. Provenance, "
        "not populatedness: an ISEE threshold parsed out of a sentence and one "
        "read from a numeric field look identical here once extracted, but "
        "only the second means the publishing body is actually emitting "
        "machine-evaluable data. The Data Readiness Score depends on this "
        "distinction, so no extractor may set it — only a connector reading a "
        "genuinely typed source field.",
    )

    @model_validator(mode="after")
    def check_ranges(self) -> Requirements:
        if self.isee_min is not None and self.isee_max is not None:
            if self.isee_min > self.isee_max:
                raise ValueError("isee_min cannot exceed isee_max")
        if self.eta_min is not None and self.eta_max is not None:
            if self.eta_min > self.eta_max:
                raise ValueError("eta_min cannot exceed eta_max")
        return self

    @property
    def is_empty(self) -> bool:
        """True when no criterion at all was captured.

        Such a record cannot be matched on anything but text similarity, and
        the Data Readiness Score penalises the publishing body for it.
        """
        return not any(
            [
                self.isee_max is not None,
                self.isee_min is not None,
                self.eta_min is not None,
                self.eta_max is not None,
                self.nucleo_min is not None,
                self.figli_minori_required is not None,
                self.disabilita_required is not None,
                self.employment_status,
                self.other,
            ]
        )


class RecoveryLevel(str, Enum):
    """D-16: which rung of the recovery ladder a record landed on.

    This is instrumentation about how closed the comune's data was, never a
    signal `match/engine.py` may read (D-16 constraint) — it must not move a
    verdict or a criterion state.

    L1_MANUALE     — nothing machine-readable recovered; the citizen must
                     open the source document(s) themselves.
    L2_ESTRATTO    — the body or a linked PDF had readable text and at least
                     one quote-gated requirement was recovered from it.
    L3_ILLEGGIBILE — a PDF exists but yielded no usable text (scanned,
                     image-only, encrypted, or a parse failure). Worse than
                     L1_MANUALE, not the same: the diagnosis is "nobody can
                     read this," not "we have not read it yet." Must never be
                     merged into L1_MANUALE.
    """

    L1_MANUALE = "L1_manuale"
    L2_ESTRATTO = "L2_estratto"
    L3_ILLEGGIBILE = "L3_illeggibile"


class PdfSkip(BaseModel):
    """One PDF attachment that was not opened, and why (D-16).

    Every skip is logged explicitly (D-15) — a silent skip would understate
    the recovery cost, which is precisely the number this instrumentation
    exists to report honestly.
    """

    url: str
    reason: str


class Source(BaseModel):
    """Provenance. Every claim TreasureIQ makes must be traceable back here."""

    ente: str = Field(description="Publishing body, e.g. 'Comune di Albano Laziale'.")
    ente_codice_istat: str | None = Field(
        default=None, description="ISTAT code, the join key across datasets."
    )
    connector: str = Field(
        description="Which ingestion connector produced this record, e.g. "
        "'wp_rest', 'ckan', 'html_scrape'. Determines baseline trust."
    )
    url: HttpUrl = Field(description="Canonical human-readable page.")
    api_url: HttpUrl | None = Field(
        default=None, description="Machine-readable endpoint, when one exists."
    )
    fetched_at: datetime
    raw_hash: str = Field(
        description="Hash of the raw payload, for change detection and audit."
    )


class Opportunity(BaseModel):
    """A single thing a citizen could benefit from or contribute to."""

    spec_version: str = SPEC_VERSION

    id: str = Field(
        description="Stable synthetic ID: '{connector}:{ente_istat}:{source_id}'."
    )
    title: str = Field(min_length=3)
    summary: str | None = Field(
        default=None, description="Short plain-language description, <= 400 chars."
    )
    body: str | None = Field(default=None, description="Full text, cleaned of markup.")

    kind: OpportunityKind
    targets: list[TargetGroup] = Field(default_factory=list)

    requirements: Requirements = Field(default_factory=Requirements)
    amount: Money | None = None

    opens_at: date | None = None
    deadline: date | None = Field(
        default=None,
        description="Application deadline. None may mean 'always open' OR "
        "'not published' — disambiguated by `deadline_confidence`.",
    )
    deadline_confidence: Confidence | None = None

    source: Source
    confidence: Confidence = Field(
        description="Trust level of the structured fields as a whole."
    )
    livello: Livello = Field(
        default=Livello.COMUNALE,
        description="Administrative tier that published this record (D-20). "
        "Defaulted to COMUNALE so existing municipal seeds validate unchanged.",
    )
    extraction_notes: list[str] = Field(
        default_factory=list,
        description="What the extractor was unsure about. Surfaced in the UI "
        "so the citizen knows where the machine guessed.",
    )

    # -- D-16/D-17 recovery-cost instrumentation -----------------------------
    # Optional, `None` by default so seeds written before this existed keep
    # validating unchanged. Populated only by connectors that actually
    # measured a recovery attempt (currently `ingest/wp_pages.py`); every
    # other connector leaves them unset. Instrumentation ONLY — nothing here
    # may be read by `match/engine.py` or influence a verdict, a criterion
    # state, or the D-05 quote-gate. A value that was not measured is `None`,
    # never a guessed zero.
    recovery_level: RecoveryLevel | None = Field(
        default=None,
        description="Which rung of the D-16 recovery ladder this record "
        "landed on. None when unmeasured.",
    )
    pdfs_linked: int | None = Field(
        default=None, description="PDF attachments found linked from the body."
    )
    pdfs_opened: int | None = Field(
        default=None,
        description="Of those linked, how many yielded usable text.",
    )
    pdfs_skipped: list[PdfSkip] | None = Field(
        default=None,
        description="PDFs not opened, each with its reason (cap, size, "
        "download failure, unreadable...).",
    )
    chars_processed: int | None = Field(
        default=None,
        description="Characters of assembled corpus actually handed to the "
        "extractor for this record.",
    )
    extraction_seconds: float | None = Field(
        default=None,
        description="Wall-clock time spent recovering this record's "
        "criteria (PDF fetch/parse + extraction attempt).",
    )
    requirements_recovered: int | None = Field(
        default=None,
        description="Count of quote-gated requirement fields that survived "
        "into `requirements` for this record. None when extraction never "
        "ran; a real 0 when it ran and recovered nothing.",
    )

    @field_validator("summary")
    @classmethod
    def trim_summary(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        return v[:400]

    @property
    def requires_human_verification(self) -> bool:
        """Whether the citizen must check the source before relying on this.

        True unless the publishing body declared structured criteria. This is
        intentionally conservative: a false 'you qualify' costs a citizen a
        wasted application and real trust, so the burden of proof sits with
        the data, not the user.
        """
        return self.confidence is not Confidence.DECLARED or self.requirements.is_empty

    @property
    def is_expired(self) -> bool:
        return self.deadline is not None and self.deadline < date.today()


ISEE = Annotated[Decimal, Field(ge=0, le=Decimal("500000"))]


class CitizenProfile(BaseModel):
    """The citizen side of the match.

    In production these fields would be populated from SPID/CIE attributes and
    the INPS ISEE attestation. In this MVP they are entered manually behind a
    mock login — see README for the substitution path.

    Deliberately minimal: TreasureIQ asks for the least it needs to match, and
    nothing that would make the profile a juicy target if the DB leaked.
    """

    codice_fiscale: str | None = Field(
        default=None,
        description="Optional even in production: matching never requires it.",
    )
    comune_istat: str | None = Field(
        default=None,
        description="Residency, the primary hard filter. None means 'not yet stated' "
        "— see matching rules.",
    )
    comune_nome: str | None = Field(default=None)

    eta: int | None = Field(default=None, ge=0, le=130)
    isee: ISEE | None = Field(
        default=None, description="None means 'not declared' — see matching rules."
    )
    nucleo_familiare: int | None = Field(default=None, ge=1)
    figli_minori: int | None = Field(default=None, ge=0)
    disabilita: bool | None = None
    employment_status: EmploymentStatus | None = None

    interests: list[TargetGroup] = Field(
        default_factory=list,
        description="Opt-in interests for the 'contribute' side: volunteering, "
        "consultations, causes worth supporting.",
    )

    @field_validator("codice_fiscale")
    @classmethod
    def normalise_cf(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if len(v) != 16:
            raise ValueError("codice fiscale must be 16 characters")
        return v
