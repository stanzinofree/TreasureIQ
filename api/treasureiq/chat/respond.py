"""Turns one citizen chat message into an answer, with the engine deciding.

The contract (`.kapi/spec.md` D-01, D-05, D-09) is narrow on purpose: the
runtime model does intent extraction (`treasureiq.chat.intent`) and, at the
very end, rephrases strings `match/engine.py` already produced. It never
emits a verdict and never states a number that is not already sitting in a
`CriterionResult.detail` or `summarise()` string.

Anonymous by default (D-09): with no session cookie, a `CitizenProfile` is
built from whatever slots the citizen volunteered in their message, with
every other field left `None` rather than guessed (R-9: an attribute the
citizen did not state must reach the engine as unknown, never as a
plausible default). `match/engine.py` now guards every profile-side field
with its own None-check, so this module hands it real `None`s and lets it
resolve the corresponding criterion to UNKNOWN_PROFILE itself — there is no
placeholder value and no local re-derivation of the verdict rule; the
engine is the only place that rule lives.

`comune_istat`/`comune_nome` are resolved from `intent.comune_hint` — the
one comune this chat can answer for (Albano Laziale) if the citizen names
it, otherwise left unknown. When residency is the one thing standing
between an anonymous citizen and a clean answer, `build_chat_answer` asks a
single clarifying question (D-09) rather than asserting a residency it was
never told; see `_is_residency_decisive` below.

`data_gap` is typed, not prose, and computed here from three deterministic
signals only: whether the model recognised a topic, whether any seed record
matched it by keyword, and whether the matched records carry any evaluable
criterion at all. The model never sets `data_gap` itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from treasureiq.chat.intent import ChatIntent, Topic, TOPIC_KEYWORDS, extract_intent
from treasureiq.extract.providers import LLMProvider, load_provider
from treasureiq.match.engine import (
    CriterionState,
    MatchResult,
    Verdict,
    match,
    summarise,
)
from treasureiq.schema import CitizenProfile, Opportunity

logger = logging.getLogger(__name__)

#: FastAPI's own 422 fires before this module ever sees the message; this
#: constant is the single source of truth both the route and this module
#: check against, so the two can never drift.
MAX_MESSAGE_CHARS = 1000

#: The only comune this chat can currently answer for — see the module
#: docstring. Kept here (not re-imported from api.py) to avoid a circular
#: import between the route module and this one.
DEFAULT_COMUNE_ISTAT = "058003"
DEFAULT_COMUNE_NOME = "Albano Laziale"

#: How many ranked matches ride along in one chat answer. Kept small: this is
#: a chat bubble, not the `/opportunita` table.
MAX_MATCHES_IN_REPLY = 3

VERBALISE_SYSTEM_PROMPT = """Riscrivi in italiano naturale, breve e cordiale, le frasi \
che ricevi qui sotto, come se le stessi spiegando di persona a uno sportello. Non \
aggiungere numeri, soglie, nomi di servizi, scadenze o giudizi di eleggibilità che non \
siano già presenti nel testo ricevuto: il tuo unico compito è renderlo più scorrevole, \
non arricchirlo. Se non sei sicuro di una riformulazione, restituisci il testo così \
com'è. Restituisci solo il testo riscritto, nessun commento."""


class VerbalisedReply(BaseModel):
    text: str = Field(max_length=1000)


@dataclass
class RecoveryStats:
    """D-17 instrumentation, read defensively from optional seed fields.

    `recovery_level`/`extraction_seconds` etc. are written by the (concurrent)
    ingestion arm and may be absent on any given record. Absence must render
    as `None`, never `0` — an unmeasured page is not a page that cost nothing.
    """

    seconds_total: float | None
    seconds_avg_comune: float | None
    levels: dict[str, int] = field(default_factory=dict)


@dataclass
class ChatAnswer:
    reply: str
    topic: Topic
    data_gap: str | None
    needs_clarification: bool
    matches: list[MatchResult]
    spid_required: bool
    spid_reason: str | None


def _resolve_comune(*, hint: str | None) -> tuple[str | None, str | None]:
    """Match a citizen-stated comune name against the one comune this chat
    can actually answer for.

    Deliberately narrow: this is not a comuni directory, so anything that
    does not clearly name Albano Laziale stays unresolved (`None, None`)
    rather than being asserted as a match or a mismatch — see R-9. Leaving
    it unresolved is safe because `match/engine.py`'s residency guard turns
    an unknown `comune_istat` into UNKNOWN_PROFILE, never into a verdict.
    """
    if hint is None:
        return None, None
    if "albano" in hint.strip().casefold():
        return DEFAULT_COMUNE_ISTAT, DEFAULT_COMUNE_NOME
    return None, None


def _profile_from_slots(*, intent: ChatIntent) -> CitizenProfile:
    """Build an anonymous profile from whatever the citizen volunteered.

    Every field the citizen did not state is handed to the engine as a real
    `None` (R-9) — `CitizenProfile` and `match/engine.py` both accept that
    now, so there is nothing here to reconcile afterwards.
    """
    slots = intent.slots
    comune_istat, comune_nome = _resolve_comune(hint=intent.comune_hint)
    return CitizenProfile(
        comune_istat=comune_istat,
        comune_nome=comune_nome,
        eta=slots.eta,
        # `str(float)` round-trips exactly through `Decimal` for the plain
        # decimal ISEE figures a citizen would type; see `ProfileSlots.isee`
        # for why the slot itself is a `float`, not a `Decimal`.
        isee=Decimal(str(slots.isee)) if slots.isee is not None else None,
        nucleo_familiare=slots.nucleo_familiare,
        figli_minori=slots.figli_minori,
        disabilita=slots.disabilita,
        employment_status=slots.employment_status,
    )


def _is_residency_decisive(result: MatchResult) -> bool:
    """Whether the citizen's comune is the only thing standing between them
    and a clean answer for this opportunity (D-09), mirroring
    `_is_spid_decisive` below but for the one profile field a chat citizen
    can resolve just by naming their comune, without SPID/CIE. Decisive only
    when residency is UNKNOWN_PROFILE and nothing else about the record is
    unresolved: an opportunity already blocked or gapped elsewhere would not
    become a clean answer even if residency were known.
    """
    if result.verdict is Verdict.NOT_ELIGIBLE:
        return False
    residency = next((c for c in result.criteria if c.key == "residenza"), None)
    if residency is None or residency.state is not CriterionState.UNKNOWN_PROFILE:
        return False
    other_unresolved = [
        c
        for c in result.criteria
        if c.key != "residenza"
        and c.state in (CriterionState.UNKNOWN_SOURCE, CriterionState.UNKNOWN_PROFILE)
    ]
    return not other_unresolved and not result.opportunity.requirements.other


def _search_opportunities(*, records: list[Opportunity], topic: Topic) -> list[Opportunity]:
    """Deterministic keyword search — the retrieval step, not the model.

    Plain lowercase substring matching over title/summary/body. This is what
    decides which opportunities are even worth handing to `match/engine.py`;
    it never decides eligibility.
    """
    keywords = TOPIC_KEYWORDS.get(topic, ())
    if not keywords:
        return []
    hits: list[Opportunity] = []
    for opportunity in records:
        haystack = " ".join(
            part for part in (opportunity.title, opportunity.summary, opportunity.body) if part
        ).lower()
        if any(keyword in haystack for keyword in keywords):
            hits.append(opportunity)
    return hits


def _is_spid_decisive(result: MatchResult) -> tuple[bool, str | None]:
    """Whether identity is the *only* thing standing between this citizen and
    a clean answer for this one opportunity (D-09). Computed from
    `result.criteria` alone: an `UNKNOWN_PROFILE` criterion is decisive only
    when nothing else about the record is unresolved — no `UNKNOWN_SOURCE`
    criterion, no free-text `other` requirement, and the opportunity is not
    already a hard `NOT_ELIGIBLE`. If the comune's own data is also
    incomplete, resolving identity would not actually produce a certain
    verdict, so escalating to SPID would be a false promise.
    """
    if result.verdict is Verdict.NOT_ELIGIBLE:
        return False, None
    unknown_profile = [c for c in result.criteria if c.state is CriterionState.UNKNOWN_PROFILE]
    if not unknown_profile:
        return False, None
    unknown_source = [c for c in result.criteria if c.state is CriterionState.UNKNOWN_SOURCE]
    if unknown_source or result.opportunity.requirements.other:
        return False, None
    labels = ", ".join(c.label for c in unknown_profile)
    reason = (
        f"Per questa opportunità manca solo la verifica di: {labels}. "
        "Accedi con SPID/CIE per avere una risposta certa."
    )
    return True, reason


def _engine_lines(*, results: list[MatchResult]) -> list[str]:
    """The only text the verbalisation model is ever allowed to see or echo."""
    return [f"- {r.opportunity.title}: {summarise(r)}" for r in results]


def _fallback_reply(*, results: list[MatchResult]) -> str:
    """Deterministic, model-free reply. Always available, always correct."""
    return " ".join(_engine_lines(results=results))


async def _verbalise(*, results: list[MatchResult], provider: LLMProvider) -> str:
    """Rephrase engine strings. Falls back to them verbatim if the model fails.

    This is the fallback D-01/D-06 require explicitly: if Ollama is down or
    the call errors for any reason, the endpoint must still answer, using the
    deterministic `summarise()`-derived text rather than 500ing.
    """
    fallback = _fallback_reply(results=results)
    try:
        out = await provider.aparse(
            system=VERBALISE_SYSTEM_PROMPT,
            user="\n".join(_engine_lines(results=results)),
            output_model=VerbalisedReply,
        )
        text = out.text.strip()
        return text or fallback
    except Exception:
        logger.warning(
            "chat verbalisation failed, falling back to deterministic summary",
            exc_info=True,
        )
        return fallback


def compute_recovery_stats(
    *, comune_records: list[Opportunity], answer_records: list[Opportunity]
) -> RecoveryStats:
    """D-17: recovery-cost instrumentation for this answer, read defensively.

    `comune_records` is every record for the comune (for the running average);
    `answer_records` is just the opportunities surfaced in this one answer.
    Every B4-written field is read with `getattr(..., None)` because B4 is
    writing the seed concurrently and older snapshots on disk simply won't
    have them yet — absence must stay `None`, never collapse to `0`.
    """

    def _seconds(records: list[Opportunity]) -> list[float]:
        values = []
        for record in records:
            value = getattr(record, "extraction_seconds", None)
            if value is not None:
                values.append(float(value))
        return values

    answer_seconds_values = _seconds(answer_records)
    seconds_total = sum(answer_seconds_values) if answer_seconds_values else None

    comune_seconds_values = _seconds(comune_records)
    seconds_avg_comune = (
        sum(comune_seconds_values) / len(comune_seconds_values)
        if comune_seconds_values
        else None
    )

    levels: dict[str, int] = {}
    for record in answer_records:
        level = getattr(record, "recovery_level", None)
        if level is None:
            continue
        key = level.value if hasattr(level, "value") else str(level)
        levels[key] = levels.get(key, 0) + 1

    return RecoveryStats(
        seconds_total=seconds_total,
        seconds_avg_comune=seconds_avg_comune,
        levels=levels,
    )


async def build_chat_answer(
    *,
    message: str,
    profile: CitizenProfile | None,
    records: list[Opportunity],
    today: date | None = None,
) -> ChatAnswer:
    """Answer one citizen turn. Never raises for model unavailability.

    `records` is the full, already-loaded set of opportunities for the
    citizen's comune (Albano, currently the only one with data) — this
    function only filters and evaluates, it never fetches.
    """
    provider: LLMProvider = load_provider(role="chat")
    intent = await extract_intent(message=message, provider=provider)

    if intent.topic is Topic.SCONOSCIUTO:
        return ChatAnswer(
            reply=(
                "Non sono riuscito a collegare la tua richiesta a un servizio del "
                "Comune di Albano Laziale. Puoi provare a riformularla, oppure "
                "rivolgerti direttamente all'URP del Comune per essere indirizzato "
                "all'ufficio competente."
            ),
            topic=intent.topic,
            data_gap="none_found",
            needs_clarification=True,
            matches=[],
            spid_required=False,
            spid_reason=None,
        )

    active_profile = profile or _profile_from_slots(intent=intent)
    candidates = _search_opportunities(records=records, topic=intent.topic)

    if not candidates:
        return ChatAnswer(
            reply=(
                "Su questo argomento il Comune non ha pubblicato dati: non significa "
                "che il servizio non esista, ma che non risulta scritto in una forma "
                "che questo sistema può leggere. Ti consiglio di contattare l'URP per "
                "un riscontro diretto."
            ),
            topic=intent.topic,
            data_gap="not_published",
            needs_clarification=False,
            matches=[],
            spid_required=False,
            spid_reason=None,
        )

    # Always evaluate every candidate (`include_ineligible=True`): the citizen
    # still deserves to know *why* they don't qualify, per `match.engine`'s
    # own design, if every candidate turns out NOT_ELIGIBLE.
    raw_results = match(candidates, active_profile, today=today, include_ineligible=True)
    results = [r for r in raw_results if r.verdict is not Verdict.NOT_ELIGIBLE]
    if not results:
        results = raw_results

    top = results[:MAX_MATCHES_IN_REPLY]

    if profile is None and intent.comune_hint is None and any(
        _is_residency_decisive(r) for r in top
    ):
        # Anonymous, comune never stated, and residency is the one thing
        # standing between the citizen and a clean answer for at least one
        # match (D-09): ask once, rather than asserting a residency nobody
        # confirmed (R-9). One question maximum — this endpoint is
        # single-turn and keeps no dialogue state, so it never asks twice
        # about the same message.
        return ChatAnswer(
            reply="In quale comune vivi?",
            topic=intent.topic,
            data_gap=None,
            needs_clarification=True,
            matches=[],
            spid_required=False,
            spid_reason=None,
        )

    if profile is None and intent.comune_hint is not None and any(
        _is_residency_decisive(r) for r in top
    ):
        # The citizen named a comune this chat could not match to Albano
        # Laziale (`_resolve_comune`), so residency is still unresolved —
        # but they already answered once, and this endpoint does not build a
        # multi-turn dialogue to ask again. Answer generically and point to
        # the office that can actually check.
        return ChatAnswer(
            reply=(
                "Da qui non riesco a verificare il tuo comune di residenza. "
                "Per sapere con certezza se hai diritto a questo servizio, "
                "rivolgiti all'URP del Comune di Albano Laziale."
            ),
            topic=intent.topic,
            data_gap=None,
            needs_clarification=False,
            matches=top,
            spid_required=False,
            spid_reason=None,
        )

    if top and all(
        all(c.state is CriterionState.UNKNOWN_SOURCE for c in r.criteria) for r in top
    ):
        # The comune published the topic but not one evaluable criterion for
        # it: a data gap, not "nothing found".
        return ChatAnswer(
            reply=_fallback_reply(results=top),
            topic=intent.topic,
            data_gap="not_published",
            needs_clarification=False,
            matches=top,
            spid_required=False,
            spid_reason=None,
        )

    spid_required = False
    spid_reason = None
    for result in top:
        decisive, reason = _is_spid_decisive(result)
        if decisive:
            spid_required, spid_reason = True, reason
            break

    reply = await _verbalise(results=top, provider=provider)

    return ChatAnswer(
        reply=reply,
        topic=intent.topic,
        data_gap=None,
        needs_clarification=False,
        matches=top,
        spid_required=spid_required,
        spid_reason=spid_reason,
    )
