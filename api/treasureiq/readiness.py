"""Data Readiness Score — how machine-usable one comune's open data actually is.

The score exists because TreasureIQ's central claim is falsifiable, and should
be. Anyone can assert that Italian PAs publish badly structured data. This
module measures it, per comune, from what the ingestion actually recovered, and
says exactly which field would need filling to raise the number.

The framing matters. TreasureIQ does not propose a new standard: the Design
Comuni Italia WordPress theme, which comuni already run, ships a `servizio`
post type with a `_dci_servizio_vincoli` metabox built to hold eligibility
constraints. On Albano Laziale that field is present on all 32 services and
filled on one. So the ask to a comune is not "adopt our schema" — it is "fill
the field your own theme already gives you". That is a much smaller ask, and
this score is what makes it concrete.

Scores are computed from ingestion evidence only. Nothing here is hand-tuned
per comune, so the comparison between neighbouring comuni is meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from treasureiq.schema import Confidence, Opportunity

#: Dimension weights, summing to 100.
#:
#: Structured eligibility is weighted highest on purpose: it is the single
#: property that decides whether a citizen can be matched automatically at all.
#: A comune with a beautiful API and no eligibility fields is, for this
#: purpose, not much better than a PDF.
WEIGHTS = {
    "machine_readable": 25,
    "structured_eligibility": 35,
    "record_completeness": 20,
    "national_catalogue": 10,
    "freshness": 10,
}

#: Records older than this stop counting as fresh. Chosen to be roughly one
#: administrative year: municipal benefits are largely annual, so a catalogue
#: untouched for longer than this is probably stale rather than stable.
FRESHNESS_HORIZON = timedelta(days=400)


class Grade(str, Enum):
    """Coarse band, for display. Thresholds are deliberately unforgiving."""

    ASSENTE = "assente"  # 0-19
    MINIMA = "minima"  # 20-39
    PARZIALE = "parziale"  # 40-59
    BUONA = "buona"  # 60-79
    OTTIMA = "ottima"  # 80-100

    @classmethod
    def from_score(cls, score: float) -> Grade:
        if score < 20:
            return cls.ASSENTE
        if score < 40:
            return cls.MINIMA
        if score < 60:
            return cls.PARZIALE
        if score < 80:
            return cls.BUONA
        return cls.OTTIMA


@dataclass
class DimensionScore:
    """One scored dimension, with the evidence that produced it."""

    key: str
    label: str
    earned: float
    weight: int
    evidence: str
    #: What the publishing body would have to do to earn the rest. Empty when
    #: the dimension is already full — the point of the score is to be
    #: actionable, so a gap without a remedy is a bug in this module.
    remedy: str = ""

    @property
    def ratio(self) -> float:
        return self.earned / self.weight if self.weight else 0.0


@dataclass
class ReadinessReport:
    ente: str
    codice_istat: str
    total_records: int
    dimensions: list[DimensionScore] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(sum(d.earned for d in self.dimensions), 1)

    @property
    def grade(self) -> Grade:
        return Grade.from_score(self.score)

    @property
    def gaps(self) -> list[DimensionScore]:
        """Unearned dimensions, worst first — the to-do list for the comune."""
        incomplete = [d for d in self.dimensions if d.ratio < 1.0]
        return sorted(incomplete, key=lambda d: d.weight - d.earned, reverse=True)

    def summary(self) -> str:
        lines = [
            f"{self.ente} — {self.score}/100 ({self.grade.value}), "
            f"{self.total_records} record"
        ]
        for d in self.dimensions:
            lines.append(f"  {d.earned:5.1f}/{d.weight:<3} {d.label}: {d.evidence}")
        return "\n".join(lines)


def _score_machine_readable(records: list[Opportunity]) -> DimensionScore:
    """Can a machine fetch this catalogue at all, and in what shape?

    Graded by transport, because that is what determines whether ingestion is
    reliable or a scraping arms race.
    """
    weight = WEIGHTS["machine_readable"]
    connectors = {r.source.connector for r in records}

    if "wp_rest" in connectors or "ckan" in connectors:
        return DimensionScore(
            key="machine_readable",
            label="Dati accessibili via API",
            earned=weight,
            weight=weight,
            evidence="API JSON pubblica e stabile",
        )
    if "html_scrape" in connectors:
        return DimensionScore(
            key="machine_readable",
            label="Dati accessibili via API",
            earned=weight * 0.3,
            weight=weight,
            evidence="solo pagine HTML, nessuna API",
            remedy=(
                "Esporre i servizi via API. Il tema Design Comuni Italia lo fa "
                "già di serie tramite /wp-json/wp/v2/servizi: spesso basta "
                "non disabilitarlo."
            ),
        )
    return DimensionScore(
        key="machine_readable",
        label="Dati accessibili via API",
        earned=0.0,
        weight=weight,
        evidence="nessuna fonte leggibile da una macchina",
        remedy="Pubblicare i servizi in un formato strutturato accessibile via HTTP.",
    )


def _score_structured_eligibility(records: list[Opportunity]) -> DimensionScore:
    """The dimension that decides whether automated matching is possible.

    Two distinct failures get separate treatment here, because they have
    different owners and different remedies:

    * The comune left the eligibility field empty. That is the comune's gap,
      and the remedy is to fill a field its own theme already provides.
    * The comune filled it, but the field is free text, so the criteria still
      have to be recovered by a language model before anything can act on
      them. That is the *standard's* gap. Design Comuni Italia's
      `_dci_servizio_vincoli` is a prose metabox, not typed fields — so on
      Albano's one populated record the criteria ("devono aver compiuto 18
      anni", residency in the comune) are perfectly clear to a reader and
      still not machine-evaluable without inference.

    A populated-but-prose record therefore earns partial credit: the comune
    did its part, the format did not. Crucially, credit is based on whether
    the *source declared* the field — never on whether TreasureIQ's own
    extractor managed to parse it. Charging a comune for our parser's misses
    would make the score measure us instead of them.
    """
    weight = WEIGHTS["structured_eligibility"]
    #: Share of the dimension earned by prose that a human can read but a
    #: machine must infer from. Deliberately generous — filling the field is
    #: real work and real progress — but capped below 1.0 because a citizen
    #: still cannot be matched automatically without an inference step.
    PROSE_CREDIT = 0.5

    if not records:
        return DimensionScore(
            key="structured_eligibility",
            label="Requisiti dichiarati in campi strutturati",
            earned=0.0,
            weight=weight,
            evidence="nessun record",
            remedy="Pubblicare almeno un servizio.",
        )

    n = len(records)
    declared = [r for r in records if r.confidence is Confidence.DECLARED]
    # Among declared records, those whose criteria are typed rather than prose.
    # No Italian municipal source emits these today; the branch exists so the
    # score can register the improvement when one finally does.
    typed = [r for r in declared if r.requirements.source_typed]
    prose = [r for r in declared if not r.requirements.source_typed]

    earned = weight * (len(typed) + PROSE_CREDIT * len(prose)) / n
    empty = n - len(declared)

    remedies: list[str] = []
    if empty:
        remedies.append(
            f"Compilare il campo requisiti sui {empty} servizi che lo lasciano "
            f"vuoto. Il modello Design Comuni Italia lo prevede già come "
            f"'_dci_servizio_vincoli': il campo esiste, non serve adottare "
            f"nessuno standard nuovo."
        )
    if prose:
        n_prose = len(prose)
        # Only the noun agrees: "i requisiti sono compilati" stays plural
        # whichever way the count goes.
        servizi = "servizio" if n_prose == 1 else "servizi"
        remedies.append(
            f"Su {n_prose} {servizi} i requisiti sono compilati ma in prosa "
            f"libera: restano leggibili da una persona, non da un motore di "
            f"matching. Servono campi tipizzati (soglia ISEE, età, nucleo) "
            f"accanto al testo descrittivo."
        )

    return DimensionScore(
        key="structured_eligibility",
        label="Requisiti dichiarati in campi strutturati",
        earned=earned,
        weight=weight,
        evidence=(
            f"{len(typed)}/{n} tipizzati, {len(prose)}/{n} in prosa, "
            f"{empty}/{n} non dichiarati"
        ),
        remedy=" ".join(remedies),
    )


def _score_record_completeness(records: list[Opportunity]) -> DimensionScore:
    """Are the fields a citizen needs actually populated?

    Deadline, amount, and audience are what turn a service listing into
    something a person can act on. Averaged per record so a catalogue can't
    score well by having one perfect entry.
    """
    weight = WEIGHTS["record_completeness"]
    if not records:
        return DimensionScore(
            key="record_completeness",
            label="Completezza dei singoli record",
            earned=0.0,
            weight=weight,
            evidence="nessun record",
        )

    with_deadline = sum(1 for r in records if r.deadline is not None)
    with_amount = sum(1 for r in records if r.amount is not None)
    with_summary = sum(1 for r in records if r.summary)
    n = len(records)
    ratio = (with_deadline / n + with_amount / n + with_summary / n) / 3

    thin = [
        name
        for name, count in (
            ("scadenza", with_deadline),
            ("importo", with_amount),
            ("descrizione sintetica", with_summary),
        )
        if count < n * 0.5
    ]

    return DimensionScore(
        key="record_completeness",
        label="Completezza dei singoli record",
        earned=weight * ratio,
        weight=weight,
        evidence=(
            f"scadenza {with_deadline}/{n}, importo {with_amount}/{n}, "
            f"descrizione {with_summary}/{n}"
        ),
        remedy=(
            f"Valorizzare i campi mancanti nella maggioranza dei servizi: "
            f"{', '.join(thin)}."
            if thin
            else ""
        ),
    )


def _score_national_catalogue(
    records: list[Opportunity], datasets_on_dati_gov: int
) -> DimensionScore:
    """Is any of this discoverable outside the comune's own website?

    A catalogue that only exists on one municipal site cannot be found by any
    aggregator, comparison tool, or citizen who does not already know the URL.
    Publication to dati.gov.it is what makes it part of the commons.
    """
    weight = WEIGHTS["national_catalogue"]
    if datasets_on_dati_gov > 0:
        return DimensionScore(
            key="national_catalogue",
            label="Presenza nel catalogo nazionale",
            earned=weight,
            weight=weight,
            evidence=f"{datasets_on_dati_gov} dataset su dati.gov.it",
        )
    return DimensionScore(
        key="national_catalogue",
        label="Presenza nel catalogo nazionale",
        earned=0.0,
        weight=weight,
        evidence="nessun dataset su dati.gov.it",
        remedy=(
            "Pubblicare il catalogo dei servizi su dati.gov.it. Senza questo "
            "passaggio i dati esistono ma non sono trovabili da nessun "
            "aggregatore."
        ),
    )


def _score_freshness(records: list[Opportunity], today: date | None = None) -> DimensionScore:
    """Is the catalogue maintained, or was it published once and abandoned?"""
    weight = WEIGHTS["freshness"]
    if not records:
        return DimensionScore(
            key="freshness",
            label="Aggiornamento del catalogo",
            earned=0.0,
            weight=weight,
            evidence="nessun record",
        )

    today = today or date.today()
    cutoff = today - FRESHNESS_HORIZON
    dated = [r for r in records if r.opens_at is not None]
    if not dated:
        return DimensionScore(
            key="freshness",
            label="Aggiornamento del catalogo",
            earned=0.0,
            weight=weight,
            evidence="nessuna data di pubblicazione nei record",
            remedy="Esporre la data di pubblicazione o ultimo aggiornamento.",
        )

    recent = sum(1 for r in dated if r.opens_at and r.opens_at >= cutoff)
    ratio = recent / len(dated)
    return DimensionScore(
        key="freshness",
        label="Aggiornamento del catalogo",
        earned=weight * ratio,
        weight=weight,
        evidence=f"{recent}/{len(dated)} record aggiornati negli ultimi 13 mesi",
        remedy=("Rimuovere o archiviare i servizi non più attivi." if ratio < 1 else ""),
    )


def score_comune(
    *,
    ente: str,
    codice_istat: str,
    records: list[Opportunity],
    datasets_on_dati_gov: int = 0,
    today: date | None = None,
) -> ReadinessReport:
    """Compute the full readiness report for one comune."""
    return ReadinessReport(
        ente=ente,
        codice_istat=codice_istat,
        total_records=len(records),
        dimensions=[
            _score_machine_readable(records),
            _score_structured_eligibility(records),
            _score_record_completeness(records),
            _score_national_catalogue(records, datasets_on_dati_gov),
            _score_freshness(records, today),
        ],
    )


def compare(reports: list[ReadinessReport]) -> str:
    """Render a comparison table across comuni, best first."""
    ranked = sorted(reports, key=lambda r: r.score, reverse=True)
    width = max((len(r.ente) for r in ranked), default=10)
    lines = [f"{'Ente'.ljust(width)}  Score  Grado      Record"]
    for r in ranked:
        lines.append(
            f"{r.ente.ljust(width)}  {r.score:5.1f}  "
            f"{r.grade.value.ljust(9)}  {r.total_records}"
        )
    return "\n".join(lines)
