"""Matching a citizen against published opportunities.

The engine is deliberately boring where it can afford to be. Eligibility is
decided by explicit comparisons over the `Requirements` fields, not by a model,
because a citizen deserves a decision they can audit and because a rule that
can be read is a rule that can be corrected. The language model's job is to
*explain* a verdict this module already reached — never to reach one.

Three-valued logic is the spine of the whole thing. Every criterion resolves to
MET, NOT_MET, or UNKNOWN, and UNKNOWN is a first-class outcome rather than an
error state, because it is the single most common one in real Italian municipal
data: on Albano Laziale, 31 of 32 services declare no eligibility criteria at
all. A two-valued engine has to guess for those, and whichever way it guesses
it is wrong at scale — treat unknown as eligible and you flood people with
applications they cannot win; treat it as ineligible and you hide benefits they
are entitled to. So the engine refuses to guess and says so, which is also the
honest UI: "probabilmente si', ma il comune non pubblica la soglia — verifica".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from treasureiq.schema import (
    CitizenProfile,
    Confidence,
    Opportunity,
    Requirements,
)


class CriterionState(str, Enum):
    """Outcome of one eligibility criterion."""

    MET = "met"
    NOT_MET = "not_met"
    #: The source did not publish this criterion. Not a failure of the citizen
    #: or of the engine — a gap in the data, and reported as such.
    UNKNOWN_SOURCE = "unknown_source"
    #: The source published it but the citizen has not supplied the value.
    #: Actionable by the citizen, unlike UNKNOWN_SOURCE.
    UNKNOWN_PROFILE = "unknown_profile"


class Verdict(str, Enum):
    """Overall eligibility conclusion for one opportunity."""

    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    #: Nothing rules the citizen out, but at least one criterion is unresolved.
    #: The dominant real-world outcome; the UI must not render it as a yes.
    LIKELY = "likely"
    #: Not a single criterion could be evaluated. Distinguished from LIKELY
    #: because "we checked and found no blockers" and "we could not check
    #: anything" deserve different words in front of a citizen.
    UNDETERMINED = "undetermined"


@dataclass
class CriterionResult:
    """One evaluated criterion, in language a citizen can read."""

    key: str
    label: str
    state: CriterionState
    detail: str

    @property
    def blocks(self) -> bool:
        return self.state is CriterionState.NOT_MET


@dataclass
class MatchResult:
    opportunity: Opportunity
    verdict: Verdict
    criteria: list[CriterionResult] = field(default_factory=list)
    #: 0-100. Ranking only — never an eligibility probability, and not to be
    #: rendered as a percentage chance of success.
    relevance: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def blockers(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.blocks]

    @property
    def unresolved(self) -> list[CriterionResult]:
        return [
            c
            for c in self.criteria
            if c.state
            in (CriterionState.UNKNOWN_SOURCE, CriterionState.UNKNOWN_PROFILE)
        ]

    @property
    def needs_source_check(self) -> bool:
        """Whether the citizen should read the comune's page before applying.

        `bool(...)` is load-bearing: `x and [list]` evaluates to the list, not
        to True, so without it this property returns a list of criteria and any
        caller serialising it as a boolean fails.
        """
        return bool(
            self.verdict is not Verdict.NOT_ELIGIBLE
            and (self.unresolved or self.opportunity.requires_human_verification)
        )


# --------------------------------------------------------------------------
# Individual criteria
#
# Each returns a CriterionResult and never raises: a malformed requirement must
# degrade to UNKNOWN_SOURCE rather than break the whole match.
# --------------------------------------------------------------------------


def format_eur(amount: Decimal) -> str:
    """Format currency the way an Italian reader expects: 30.000,00 €.

    Python's thousands separator is locale-dependent and defaults to the
    English convention, which inverts the meaning of both separators for this
    audience — '30,000.00' reads as thirty euro to someone who expects the
    Italian format. Since these strings sit inside the sentence explaining why
    a citizen was excluded from a benefit, the swap is done explicitly rather
    than left to whatever locale the container happens to boot with.
    """
    formatted = f"{amount:,.2f}"  # 30,000.00
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".") + " €"


def _absent(req: Requirements, key: str, label: str, subject: str) -> CriterionResult:
    """Resolve a criterion the source left unset.

    An unset field means two very different things depending on where the data
    came from, and collapsing them is the difference between a useful engine
    and a useless one.

    When the source publishes *typed* fields, silence is informative: a comune
    that fills a structured eligibility form and leaves the age boundary empty
    is saying there is no age limit. Treating that as unknown would make every
    result provisional and `ELIGIBLE` unreachable in practice — the engine
    would answer "verifica" to everything, which is the same as answering
    nothing.

    When the criteria were recovered from prose, silence means only that the
    extractor found nothing. The constraint may well exist a paragraph further
    down. That genuinely is unknown, and must be reported as such.

    The `other` list carries the third case — a criterion the source names
    without quantifying ("richiede ISEE" with no threshold). That is recorded
    at extraction time and always downgrades the verdict, whichever branch
    this function takes.
    """
    if req.source_typed:
        return CriterionResult(
            key,
            label,
            CriterionState.MET,
            f"Il comune non pone vincoli di {subject} per questo servizio.",
        )
    return CriterionResult(
        key,
        label,
        CriterionState.UNKNOWN_SOURCE,
        f"Nessun vincolo di {subject} trovato nel testo, ma il comune non "
        f"pubblica i requisiti in forma strutturata: potrebbe non essere tutto.",
    )


def _check_residency(
    req: Requirements, profile: CitizenProfile, issuing_istat: str | None
) -> CriterionResult:
    label = "Residenza"
    if not req.residenza_required:
        return CriterionResult(
            "residenza", label, CriterionState.MET, "Non richiede la residenza."
        )

    qualifying = req.residenza_comuni or ([issuing_istat] if issuing_istat else [])
    if not qualifying:
        return CriterionResult(
            "residenza",
            label,
            CriterionState.UNKNOWN_SOURCE,
            "Il bando richiede la residenza ma non specifica in quale comune.",
        )
    if profile.comune_istat is None:
        return CriterionResult(
            "residenza",
            label,
            CriterionState.UNKNOWN_PROFILE,
            "Indica il tuo comune di residenza per verificare questo requisito.",
        )
    if profile.comune_istat in qualifying:
        return CriterionResult(
            "residenza",
            label,
            CriterionState.MET,
            f"Sei residente a {profile.comune_nome}.",
        )
    return CriterionResult(
        "residenza",
        label,
        CriterionState.NOT_MET,
        f"Riservato ai residenti di un altro comune (non {profile.comune_nome}).",
    )


def _check_isee(req: Requirements, profile: CitizenProfile) -> CriterionResult:
    label = "ISEE"
    if req.isee_max is None and req.isee_min is None:
        return _absent(req, "isee", label, "reddito (ISEE)")
    if profile.isee is None:
        return CriterionResult(
            "isee",
            label,
            CriterionState.UNKNOWN_PROFILE,
            "Aggiungi il tuo ISEE al profilo per verificare questo requisito.",
        )

    isee = Decimal(profile.isee)
    # Comparisons are exact by construction: both sides are Decimal, because a
    # citizen one euro over a threshold must get a deterministic answer rather
    # than one that depends on binary floating point.
    if req.isee_max is not None and isee > req.isee_max:
        return CriterionResult(
            "isee",
            label,
            CriterionState.NOT_MET,
            f"Il tuo ISEE ({format_eur(isee)}) supera la soglia massima "
            f"({format_eur(req.isee_max)}).",
        )
    if req.isee_min is not None and isee < req.isee_min:
        return CriterionResult(
            "isee",
            label,
            CriterionState.NOT_MET,
            f"Il tuo ISEE ({format_eur(isee)}) è sotto la soglia minima "
            f"({format_eur(req.isee_min)}).",
        )
    bound = (
        f"soglia massima di {format_eur(req.isee_max)}"
        if req.isee_max is not None
        else f"soglia minima di {format_eur(req.isee_min)}"
    )
    return CriterionResult(
        "isee", label, CriterionState.MET, f"Il tuo ISEE rientra nella {bound}."
    )


def _check_age(req: Requirements, profile: CitizenProfile) -> CriterionResult:
    label = "Età"
    if req.eta_min is None and req.eta_max is None:
        return _absent(req, "eta", label, "età")
    if profile.eta is None:
        return CriterionResult(
            "eta",
            label,
            CriterionState.UNKNOWN_PROFILE,
            "Indica la tua età per verificare questo requisito.",
        )
    if req.eta_min is not None and profile.eta < req.eta_min:
        return CriterionResult(
            "eta",
            label,
            CriterionState.NOT_MET,
            f"Richiede almeno {req.eta_min} anni (ne hai {profile.eta}).",
        )
    if req.eta_max is not None and profile.eta > req.eta_max:
        return CriterionResult(
            "eta",
            label,
            CriterionState.NOT_MET,
            f"Riservato a chi ha fino a {req.eta_max} anni (ne hai {profile.eta}).",
        )
    return CriterionResult(
        "eta", label, CriterionState.MET, f"La tua età ({profile.eta}) rientra nei limiti."
    )


def _check_household(req: Requirements, profile: CitizenProfile) -> CriterionResult:
    label = "Nucleo familiare"
    if req.nucleo_min is None:
        return _absent(req, "nucleo", label, "nucleo familiare")
    if profile.nucleo_familiare is None:
        return CriterionResult(
            "nucleo",
            label,
            CriterionState.UNKNOWN_PROFILE,
            "Indica quante persone ci sono nel tuo nucleo familiare per verificare "
            "questo requisito.",
        )
    if profile.nucleo_familiare < req.nucleo_min:
        return CriterionResult(
            "nucleo",
            label,
            CriterionState.NOT_MET,
            f"Richiede un nucleo di almeno {req.nucleo_min} persone "
            f"(il tuo ne ha {profile.nucleo_familiare}).",
        )
    return CriterionResult(
        "nucleo", label, CriterionState.MET, "Il tuo nucleo familiare rientra nei requisiti."
    )


def _check_minors(req: Requirements, profile: CitizenProfile) -> CriterionResult:
    label = "Figli minori"
    if req.figli_minori_required is None:
        return _absent(req, "figli_minori", label, "figli minori")
    if profile.figli_minori is None:
        return CriterionResult(
            "figli_minori",
            label,
            CriterionState.UNKNOWN_PROFILE,
            "Indica se hai figli minori per verificare questo requisito.",
        )
    if req.figli_minori_required and profile.figli_minori == 0:
        return CriterionResult(
            "figli_minori",
            label,
            CriterionState.NOT_MET,
            "Riservato a nuclei con figli minorenni.",
        )
    return CriterionResult(
        "figli_minori", label, CriterionState.MET, "Requisito sui figli minori soddisfatto."
    )


def _check_disability(req: Requirements, profile: CitizenProfile) -> CriterionResult:
    label = "Disabilità"
    if req.disabilita_required is None:
        return _absent(req, "disabilita", label, "disabilità")
    if profile.disabilita is None:
        return CriterionResult(
            "disabilita",
            label,
            CriterionState.UNKNOWN_PROFILE,
            "Indica se hai una condizione di disabilità per verificare questo requisito.",
        )
    if req.disabilita_required and not profile.disabilita:
        return CriterionResult(
            "disabilita",
            label,
            CriterionState.NOT_MET,
            "Richiede una condizione di disabilità certificata.",
        )
    return CriterionResult(
        "disabilita", label, CriterionState.MET, "Requisito di disabilità soddisfatto."
    )


def _check_employment(req: Requirements, profile: CitizenProfile) -> CriterionResult:
    label = "Condizione lavorativa"
    if not req.employment_status:
        return _absent(req, "lavoro", label, "condizione lavorativa")
    if profile.employment_status is None:
        return CriterionResult(
            "lavoro",
            label,
            CriterionState.UNKNOWN_PROFILE,
            "Indica la tua condizione lavorativa nel profilo.",
        )
    if profile.employment_status in req.employment_status:
        return CriterionResult(
            "lavoro",
            label,
            CriterionState.MET,
            f"La tua condizione ({profile.employment_status.value}) è ammessa.",
        )
    ammesse = ", ".join(s.value for s in req.employment_status)
    return CriterionResult(
        "lavoro",
        label,
        CriterionState.NOT_MET,
        f"Riservato a: {ammesse}.",
    )


CRITERION_CHECKS = (
    _check_isee,
    _check_age,
    _check_household,
    _check_minors,
    _check_disability,
    _check_employment,
)


# --------------------------------------------------------------------------
# Verdict and ranking
# --------------------------------------------------------------------------


def evaluate(
    opportunity: Opportunity, profile: CitizenProfile, *, today: date | None = None
) -> MatchResult:
    """Evaluate one opportunity against one citizen profile."""
    req = opportunity.requirements
    criteria = [
        _check_residency(req, profile, opportunity.source.ente_codice_istat),
        *(check(req, profile) for check in CRITERION_CHECKS),
    ]

    notes: list[str] = []
    # Unstructurable criteria are surfaced verbatim rather than silently
    # ignored: their presence is precisely why a match can't be trusted alone.
    for other in req.other:
        notes.append(f"Requisito aggiuntivo da verificare: {other}")
    notes.extend(opportunity.extraction_notes)

    blocking = [c for c in criteria if c.blocks]
    unresolved = [
        c
        for c in criteria
        if c.state in (CriterionState.UNKNOWN_SOURCE, CriterionState.UNKNOWN_PROFILE)
    ]
    met = [c for c in criteria if c.state is CriterionState.MET]

    if blocking:
        verdict = Verdict.NOT_ELIGIBLE
    elif not met:
        verdict = Verdict.UNDETERMINED
    elif unresolved or req.other:
        # Free-text criteria count as unresolved even when every structured
        # check passed: "possesso di partita IVA" can rule a citizen out just
        # as hard as an ISEE ceiling, and nothing here evaluated it.
        verdict = Verdict.LIKELY
    elif opportunity.confidence is not Confidence.DECLARED:
        # Every structured criterion passed, but the criteria themselves were
        # inferred from prose. A clean pass over guessed rules is not a yes.
        verdict = Verdict.LIKELY
        notes.append(
            "I requisiti non sono pubblicati in forma strutturata dal comune: "
            "sono stati ricavati dal testo, quindi vanno verificati."
        )
    else:
        verdict = Verdict.ELIGIBLE

    return MatchResult(
        opportunity=opportunity,
        verdict=verdict,
        criteria=criteria,
        relevance=_relevance(opportunity, profile, criteria, today=today),
        notes=notes,
    )


def _relevance(
    opportunity: Opportunity,
    profile: CitizenProfile,
    criteria: list[CriterionResult],
    *,
    today: date | None = None,
) -> float:
    """Ranking score, 0-100. Ordering only — not a probability of success.

    Weighted toward criteria that were actually *verified* rather than merely
    unblocked, so a service that positively matches the citizen outranks one
    that simply failed to state any requirements. Without that, the noisiest
    records — the ones publishing nothing — would float to the top, which is
    exactly backwards.
    """
    today = today or date.today()
    met = sum(1 for c in criteria if c.state is CriterionState.MET)
    unknown = sum(1 for c in criteria if c.state is CriterionState.UNKNOWN_SOURCE)

    score = 40.0 + 8.0 * met - 3.0 * unknown

    if opportunity.targets:
        overlap = set(opportunity.targets) & set(profile.interests)
        if overlap:
            score += 10.0

    # Declared data is worth ranking above inferred data: it is more likely to
    # be right, and rewarding it is the incentive the project wants to create.
    if opportunity.confidence is Confidence.DECLARED:
        score += 8.0
    elif opportunity.confidence is Confidence.INFERRED:
        score -= 5.0

    if opportunity.deadline is not None:
        days = (opportunity.deadline - today).days
        if days < 0:
            score -= 40.0  # expired; filtered out earlier, defensive here
        elif days <= 14:
            score += 12.0  # closing soon and still open — worth surfacing
        elif days <= 60:
            score += 5.0

    return round(max(0.0, min(100.0, score)), 1)


def match(
    opportunities: list[Opportunity],
    profile: CitizenProfile,
    *,
    today: date | None = None,
    include_ineligible: bool = False,
    include_expired: bool = False,
) -> list[MatchResult]:
    """Rank opportunities for one citizen.

    Ineligible results are dropped by default but retrievable: a citizen who
    asks "why isn't this one for me?" deserves the reason, and hiding the
    blocker teaches them nothing about what would change it.
    """
    today = today or date.today()
    results: list[MatchResult] = []

    for opportunity in opportunities:
        if not include_expired and opportunity.deadline and opportunity.deadline < today:
            continue
        result = evaluate(opportunity, profile, today=today)
        if result.verdict is Verdict.NOT_ELIGIBLE and not include_ineligible:
            continue
        results.append(result)

    # Verdict first, then relevance: a confirmed match must never sort below a
    # merely-plausible one, whatever the numbers say.
    order = {
        Verdict.ELIGIBLE: 0,
        Verdict.LIKELY: 1,
        Verdict.UNDETERMINED: 2,
        Verdict.NOT_ELIGIBLE: 3,
    }
    results.sort(key=lambda r: (order[r.verdict], -r.relevance, r.opportunity.title))
    return results


def summarise(result: MatchResult) -> str:
    """One-line citizen-facing summary. Deterministic; no model involved.

    This is the fallback the UI renders when no API key is configured, which
    means the demo tells the truth about every match without a network call.
    """
    if result.verdict is Verdict.NOT_ELIGIBLE:
        reason = result.blockers[0].detail if result.blockers else "requisiti non soddisfatti"
        return f"Non accessibile: {reason}"
    if result.verdict is Verdict.ELIGIBLE:
        return "Hai i requisiti pubblicati dal comune per accedere."
    if result.verdict is Verdict.UNDETERMINED:
        return (
            "Il comune non pubblica requisiti verificabili: "
            "controlla la pagina del servizio."
        )
    missing = len(result.unresolved)
    noun = (
        "criterio non è verificabile"
        if missing == 1
        else "criteri non sono verificabili"
    )
    return (
        f"Nessun requisito ti esclude, ma {missing} {noun}: "
        f"conferma sulla pagina del comune."
    )
