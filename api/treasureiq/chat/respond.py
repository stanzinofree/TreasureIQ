"""Turns one citizen chat message into an answer, with the engine deciding.

The contract (`.kapi/spec.md` D-01, D-05, D-09) is narrow on purpose, and has
since narrowed further: the runtime model now does intent extraction
(`treasureiq.chat.intent`) and nothing else on this rail. It emits no verdict
and states no number at all.

The rephrasing step it used to perform at the very end is gone. Its output
duplicated the card rendered directly beneath it — same title, same sentence —
so the model was being asked to disguise a repetition rather than remove one,
and it kept corrupting the figures it was handed while doing so. `_apertura`
composes the lead-in deterministically from counts instead, saying only what
the cards do not.

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

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from treasureiq.chat.intent import (
    AMBIGUOUS_ROLE_TOPICS,
    INFORMATIONAL_BY_NATURE_TOPICS,
    TOPIC_KEYWORDS,
    BeneficiaryRole,
    ChatIntent,
    QuestionKind,
    Topic,
    extract_intent,
)
from treasureiq.extract.providers import LLMProvider, load_provider
from treasureiq.integration import (
    AccessMode,
    Ente,
    cost_lines,
    diagnosis_lines,
    load_enti,
    load_websearch,
)
from treasureiq.ingest.censimento import Indirizzabilita
from treasureiq.sonda_live import comune_per_codice, leggi_orari_urp, risolvi_comune
from treasureiq.match.engine import (
    CriterionState,
    MatchResult,
    Verdict,
    match,
    summarise,
)
from treasureiq.schema import CitizenProfile, Livello, Opportunity

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


#: How many web results ride along in one INFORMAZIONE answer (D-28).
MAX_WEB_RESULTS_IN_REPLY = 3

#: Deterministic query fragment per topic, fed to `integration.load_websearch`
#: only after every institutional source is exhausted (D-28). Keyed by topic
#: rather than free text so the query a comune's own INFORMAZIONE answer runs
#: is auditable the same way `TOPIC_KEYWORDS` is: no model chooses it. A
#: topic with no entry here simply never triggers a web lookup — `None` is
#: never fabricated into a query.
WEBSEARCH_QUERY_FRAGMENTS: dict[Topic, str] = {
    Topic.RIFIUTI: "calendario raccolta differenziata",
    Topic.SOSTEGNO_UTENZE: "bonus sociale bollette requisiti",
    Topic.CONTRIBUTO_AFFITTO: "contributo affitto morosità incolpevole bando",
    Topic.MENSA_SCOLASTICA: "mensa scolastica tariffe iscrizione",
    Topic.TRASPORTO_SCOLASTICO: "trasporto scolastico scuolabus iscrizione",
    Topic.CONTRIBUTO_LIBRI: "contributo libri di testo bando",
    Topic.BORSA_STUDIO: "borsa di studio bando",
    Topic.ASSEGNO_MATERNITA: "assegno di maternità requisiti",
    Topic.VOUCHER_CONCILIAZIONE: "voucher conciliazione lavoro famiglia",
    Topic.ASSISTENZA_DISABILITA: "assistenza domiciliare disabilità",
    Topic.CONTRASSEGNO_DISABILI: "contrassegno disabili rilascio",
    Topic.ANAGRAFE_CARTA_IDENTITA: "carta d'identità elettronica appuntamento",
    Topic.ACCESSO_ATTI: "accesso agli atti modulo",
    Topic.OCCUPAZIONE_SUOLO: "occupazione suolo pubblico domanda",
    Topic.CAREGIVER_DOMICILIARE: "caregiver familiare contributo",
    Topic.MATRIMONIO_SEPARAZIONE: "matrimonio civile pubblicazioni",
    Topic.INCLUSIONE_SOCIALE: "inclusione sociale servizi sociali",
    Topic.SUAP_IMPRESE: "SUAP sportello unico attività produttive",
    Topic.AREA_VERDE: "aree verdi parchi",
    Topic.VOLONTARIATO: "volontariato albo associazioni",
}


@dataclass
class DocumentAnswer:
    title: str
    url: str


@dataclass
class OfficeAnswer:
    nome: str
    telefono: str | None
    email: str | None
    orari: str | None


@dataclass
class WebResultAnswer:
    title: str
    url: str
    non_verificato: bool = True


@dataclass
class InfoAnswer:
    """Everything an INFORMAZIONE answer carries besides its reply text —
    document, office, coverage, and the deterministic diagnosis/cost/web
    blocks composed by `integration.py` (D-24, D-28). No verdict, no
    criteria, no SPID field exists on this type at all (D-19): the shape
    itself makes the AGEVOLAZIONE-only fields impossible to smuggle in.
    """

    document: DocumentAnswer | None
    office: OfficeAnswer | None
    coverage_count: int
    diagnosis: list[str]
    integration_cost: list[str]
    web_results: list[WebResultAnswer]
    #: Letto dal portale del comune mentre il cittadino aspettava (D-32),
    #: invece che da uno snapshot curato. La differenza deve arrivare
    #: all'interfaccia come un dato, non come una sfumatura nel testo della
    #: risposta: chi legge deve poterla vedere senza doverla dedurre.
    letto_dal_vivo: bool = False


@dataclass
class ChatAnswer:
    reply: str
    topic: Topic
    kind: QuestionKind
    data_gap: str | None
    needs_clarification: bool
    matches: list[MatchResult]
    spid_required: bool
    spid_reason: str | None
    access_mode: str | None = None
    citizen_effort: int | None = None
    info: InfoAnswer | None = None


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


def _backfill_ambiguous_topic(*, intent: ChatIntent) -> ChatIntent:
    """Recover the topic for a reply to an ambiguous-role clarifying question
    (D-19 round 2) that, on its own, carries no topic word at all — e.g.
    "per me, nel mio comune Albano Laziale" answering "è per te o vuoi fare
    volontariato?" This endpoint is stateless (no dialogue history), so
    `extract_intent` sees only that second message and correctly falls back
    to `SCONOSCIUTO` there being no topic word in it.

    This is not a second classification mechanism: it never inspects the
    message text. It only uses `AMBIGUOUS_ROLE_TOPICS`, a closed, already
    deterministic mapping — if `beneficiary_role` is confirmed (R-9: only
    ever set from a marker in the citizen's own text, see
    `intent._confirm_beneficiary_role`) and exactly one topic in that
    mapping uses that role, the topic must be that one, because a role only
    exists in this schema for the topic that asked for it. Never fires when
    the role maps to more than one topic — no speculative disambiguation.
    """
    if intent.topic is not Topic.SCONOSCIUTO or intent.beneficiary_role is None:
        return intent
    matching_topics = [
        topic
        for topic, roles in AMBIGUOUS_ROLE_TOPICS.items()
        if intent.beneficiary_role in roles
    ]
    if len(matching_topics) != 1:
        return intent
    return intent.model_copy(update={"topic": matching_topics[0]})


def _tema_sostenuto(*, topic: Topic, testo: str) -> bool:
    """Whether the text actually contains a word belonging to this topic.

    Same closed keyword vocabulary `_search_opportunities` retrieves with, so
    the two cannot disagree about what a topic looks like. A topic with no
    keywords defined is treated as supported: absence of a rule is not
    evidence against the model.
    """
    parole = TOPIC_KEYWORDS.get(topic, ())
    if not parole:
        return True
    minuscolo = testo.casefold()
    return any(k in minuscolo for k in parole)


async def _eredita_dal_contesto(
    *, intent: ChatIntent, messaggio: str, storia: list[str], provider: LLMProvider
) -> ChatIntent:
    """Carry forward the comune and the subject the citizen already gave.

    A turn that supplies only a comune ("sono di Albano Laziale") has no topic
    of its own, and a turn that supplies only a follow-up ("quali sono gli
    orari?") has no comune. Read in isolation each is unanswerable, and the
    chat was reading them in isolation — so it asked for the comune twice and
    lost the subject in between.

    Both are recovered from the citizen's own earlier messages, re-extracted
    through the same closed schema rather than parsed here: whatever is
    inherited has to come from the same mechanism that would have accepted it
    when it was first said, or the two paths could disagree about what a
    sentence means.

    Nothing is inherited over something the current turn actually states —
    saying a new comune must replace the old one, not be ignored in favour of
    it.
    """
    # Empty string, not None, is what the extractor returns for "no comune
    # mentioned" — so a `is None` check inherited nothing and the chat kept
    # asking which comune it was talking to.
    serve_comune = not (intent.comune_hint or "").strip()

    # A topic the message does not support is a guess, and a guess blocks the
    # real subject from being carried forward. Asked "quali sono gli orari?"
    # the model answered `rifiuti`, a topic whose every keyword is absent from
    # those four words. The check is deterministic and uses the same closed
    # vocabulary retrieval uses: if no keyword of the assigned topic appears in
    # what the citizen actually wrote, the assignment is not evidenced and the
    # earlier subject wins.
    serve_tema = intent.topic is Topic.SCONOSCIUTO or not _tema_sostenuto(
        topic=intent.topic, testo=messaggio
    )

    if not (serve_comune or serve_tema) or not storia:
        return intent

    aggiornamenti: dict[str, object] = {}
    # Most recent first: the last thing said wins, as it would in speech.
    for passato in reversed(storia[-6:]):
        if not (serve_comune or serve_tema):
            break
        try:
            vecchio = await extract_intent(message=passato, provider=provider)
        except Exception:  # noqa: BLE001 — a failed re-read is not fatal
            continue
        if serve_comune and vecchio.comune_hint:
            aggiornamenti["comune_hint"] = vecchio.comune_hint
            serve_comune = False
        if serve_tema and vecchio.topic is not Topic.SCONOSCIUTO:
            aggiornamenti["topic"] = vecchio.topic
            serve_tema = False

    return intent.model_copy(update=aggiornamenti) if aggiornamenti else intent


def _search_opportunities(
    *,
    records: list[Opportunity],
    topic: Topic,
    role: BeneficiaryRole | None = None,
) -> list[Opportunity]:
    """Deterministic keyword search — the retrieval step, not the model.

    Plain lowercase substring matching over title/summary/body. This is what
    decides which opportunities are even worth handing to `match/engine.py`;
    it never decides eligibility.

    `role` only matters for the small set of topics in `AMBIGUOUS_ROLE_TOPICS`
    (D-19 round 2): a known role there picks a different, narrower keyword
    set than `TOPIC_KEYWORDS`, because the recipient and the volunteer read
    different documents. Every other topic ignores `role` entirely — the
    default keyword set is unaffected, so the AGEVOLAZIONE rail (which never
    passes `role`) and any non-ambiguous topic behave exactly as before.
    """
    role_keywords = AMBIGUOUS_ROLE_TOPICS.get(topic, {}).get(role) if role is not None else None
    keywords = role_keywords if role_keywords is not None else TOPIC_KEYWORDS.get(topic, ())
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


def _apertura(*, results: list[MatchResult]) -> str:
    """The sentence the assistant says before the cards.

    It used to be `"{title}: {summarise(result)}"` per result, run through the
    verbalisation model. Two problems compounded. The card underneath states
    exactly the same title and the same sentence, so the answer was given
    twice, verbatim — which is what makes a reply read as canned however it is
    worded. And the model, whose whole job was to make that duplicate sound
    different, kept altering the figures inside it, so the figure guard
    correctly threw the rewrite away and the duplicate came back anyway.

    So this stops restating the verdicts and does the job the cards cannot: it
    says how many results there are and how they divide, then hands over. No
    title, no threshold, no criterion — nothing a card repeats, and nothing a
    model needs to touch, which is why this rail no longer calls one.
    """
    if not results:
        return "Non ho trovato niente di pertinente."

    eleggibili = [r for r in results if r.verdict is Verdict.ELIGIBLE]
    esclusi = [r for r in results if r.verdict is Verdict.NOT_ELIGIBLE]
    da_confermare = [
        r for r in results if r.verdict in (Verdict.LIKELY, Verdict.UNDETERMINED)
    ]

    def plurale(n: int, uno: str, molti: str) -> str:
        return f"{n} {uno}" if n == 1 else f"{n} {molti}"

    pezzi: list[str] = []
    if eleggibili:
        pezzi.append(plurale(len(eleggibili), "ti spetta", "ti spettano"))
    if da_confermare:
        pezzi.append(plurale(len(da_confermare), "da confermare", "da confermare"))
    if esclusi:
        pezzi.append(plurale(len(esclusi), "esclusa", "escluse"))

    totale = plurale(len(results), "cosa pertinente", "cose pertinenti")
    dettaglio = ", ".join(pezzi)

    # One result needs no arithmetic read back to it: "1 cosa pertinente: 1
    # esclusa" is a sentence that counts out loud for no reason.
    if len(results) == 1:
        solo = pezzi[0].split(" ", 1)[1]
        return f"Ho trovato una cosa pertinente, {solo}. Il dettaglio qui sotto."

    return f"Ho trovato {totale}: {dettaglio}. Il dettaglio di ciascuna qui sotto."


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


# The verbalisation model is gone from this rail.
#
# Its job was to rephrase the engine's own sentences so the reply would not
# read like machine output. But the card under every reply already stated the
# same title and the same sentence, so the model was being asked to disguise a
# duplicate rather than remove it — and it kept corrupting the figures inside
# it while trying, which the figure guard then had to throw away. `_apertura`
# above says what the cards cannot say and repeats nothing they do, so there
# is nothing left here for a model to rewrite and no figure left for it to
# damage. The removed code, guard included, is in the history if a rail ever
# needs prose again.


def approfondisci_nel_comune(
    *,
    records: list[Opportunity],
    topic: Topic,
    profile: CitizenProfile | None,
    comune_nome: str,
    ente: Ente | None = None,
    today: date | None = None,
) -> tuple[list[MatchResult], str, list[WebResultAnswer]]:
    """Check the comune's own published records for a topic, and say so either
    way.

    The ordinary answer already searches municipal and national records
    together, so a benefit the comune publishes would have surfaced there —
    this does not find what the first pass missed. What it adds is the
    statement the first pass never makes: when the only answer was a national
    measure, nothing on screen said whether the comune had published anything
    of its own. A silent absence reads as "not looked for"; this turns it into
    a finding, which is the only form an absence can honestly take in a
    service whose subject is what administrations do and do not publish.

    Deterministic end to end. The topic is carried over from the answer that
    prompted it, so no model runs here and the same request always produces
    the same result.

    The last rung (D-21's `M6_web_aperto`) is only reached when the structured
    records turn up nothing: institutional pages found by search are weaker
    evidence than a published record, so they are what remains when the strong
    evidence is absent, never a supplement to it. The cache is read, never
    filled here — the fetch happened at ingestion (D-28).
    """
    comunali = [r for r in records if r.livello is Livello.COMUNALE]
    candidati = _search_opportunities(records=comunali, topic=topic)
    profilo = profile if profile is not None else CitizenProfile()
    results = match(candidati, profilo, today=today, include_ineligible=True)

    web: list[WebResultAnswer] = []
    if not comunali:
        esito = (
            f"Non abbiamo ancora nessuno snapshot dei dati pubblicati da {comune_nome}, "
            "quindi su questo tema non possiamo dire nulla sul comune."
        )
    elif not results:
        esito = (
            f"{comune_nome} non ha pubblicato nulla su questo tema fra i "
            f"{len(comunali)} servizi che abbiamo letto dal suo portale. "
            "Non significa che non esista: significa che non è scritto in un "
            "posto che si possa leggere."
        )
        web = _pagine_istituzionali(topic=topic, comune_nome=comune_nome, ente=ente)
        if web:
            esito += (
                " Cercando fra i portali istituzionali abbiamo però trovato "
                "queste pagine: non sono dati strutturati e non le abbiamo "
                "verificate, ma è da lì che conviene partire."
            )
    else:
        esito = (
            f"{comune_nome} ha pubblicato qualcosa su questo tema: "
            f"{len(results)} risultati fra i {len(comunali)} servizi letti dal "
            "suo portale."
        )
    return results, esito, web


def _host_del_comune(ente: Ente | None) -> str | None:
    """The comune's own web host, as IPA records it."""
    if ente is None or ente.ipa is None or not ente.ipa.sito:
        return None
    sito = ente.ipa.sito.strip()
    if "//" not in sito:
        sito = f"https://{sito}"
    host = urlparse(sito).hostname or ""
    return host.lower().removeprefix("www.") or None


def _e_di_un_altro_comune(url: str, *, host_proprio: str | None) -> bool:
    """Whether a page belongs to a municipality that is not this one.

    The institutional filter answers "is this a public body"; it cannot answer
    "is this *your* public body". Searching "mensa scolastica tariffe Fonte
    Nuova" returned Bologna's school-meals page and `comune.fonte.tv.it` — Fonte
    in Treviso, a different comune with a similar name — both perfectly
    institutional and both wrong for the person asking. Tariffs, deadlines and
    offices differ by comune, so another municipality's page is not weaker
    evidence about yours: it is evidence about somebody else, and acting on it
    costs a wasted trip at best.

    National and regional bodies are left alone: INPS and ARERA publish rules
    that genuinely apply everywhere, which is why they were worth reaching in
    the first place.
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host.startswith(("comune.", "comuni.", "citta.", "cittadi.")):
        return False
    return host != host_proprio


def _pagine_istituzionali(
    *, topic: Topic, comune_nome: str, ente: Ente | None = None
) -> list[WebResultAnswer]:
    """Cached institutional pages for a topic in one comune (D-28).

    Reads the cache and nothing else: the search ran at ingestion, so a
    citizen's question never reaches the network and never waits on a search
    provider's quota. A missing entry means the query was never run — or ran
    and was refused, since empty answers are deliberately not cached — and both
    are correctly reported by returning nothing rather than by searching now.
    """
    fragment = WEBSEARCH_QUERY_FRAGMENTS.get(topic)
    if fragment is None:
        return []
    entry = load_websearch(f"{fragment} {comune_nome}")
    if entry is None:
        return []
    host_proprio = _host_del_comune(ente)
    tenute = [
        r
        for r in entry.results
        if not _e_di_un_altro_comune(str(r.url), host_proprio=host_proprio)
    ]
    return [
        WebResultAnswer(title=r.title, url=str(r.url))
        for r in tenute[:MAX_WEB_RESULTS_IN_REPLY]
    ]


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


# The verbalisation model is gone from this rail.
#
# Its job was to rephrase the engine's own sentences so a reply would not read
# like machine output. But the card under every reply already stated the same
# title and the same sentence, so the model was asked to disguise a duplicate
# rather than remove one — and it kept corrupting the figures inside it while
# trying, which the figure guard then had to throw away. `_apertura` says what
# the cards cannot and repeats nothing they do, so nothing is left here for a
# model to rewrite and no figure left for it to damage. The removed code,
# guard included, is in the history if a rail ever needs prose again.

def _bare_ente_name(ente: Ente) -> str:
    """`ente.ente` minus its "Comune di " prefix, for query building and
    matching a citizen's free-text comune name."""
    return ente.ente.removeprefix("Comune di ").strip()


#: Italian toponym prefixes that turn a bare ente name into a *different*
#: place — "Marino" is a comune, "San Marino" is a different country.
#: A token-boundary match alone does not catch this ("\bMarino\b" still
#: matches inside "San Marino"), so a bare-name match immediately preceded
#: by one of these is rejected rather than accepted (see
#: `_resolve_informazione_ente`).
_TOPONYM_PREFIXES = {"san", "santa", "sant"}

#: Short forms a citizen realistically types, beyond the ente's full bare
#: name (which `_resolve_informazione_ente` always tries too). Curated by
#: hand, not derived, because a generic "first token" rule would also match
#: on "Fonte" alone — a common Italian noun ("fonte di finanziamento") that
#: must NOT resolve to Fonte Nuova. Adding a 6th ente means deciding this by
#: hand as well; the full-name fallback still works with no entry here.
_ENTE_ALIAS_TOKENS: dict[str, tuple[tuple[str, ...], ...]] = {
    "058003": (("albano",),),
    "058043": (("genzano",),),
}


def _match_token_sequence(*, tokens: list[str], sequence: tuple[str, ...]) -> bool:
    """Whether `sequence` occurs in `tokens` as a contiguous, whole-token
    run, and is not itself the tail of a longer Italian toponym (see
    `_TOPONYM_PREFIXES`)."""
    span = len(sequence)
    if span == 0:
        return False
    for start in range(len(tokens) - span + 1):
        if tuple(tokens[start : start + span]) != sequence:
            continue
        preceding = tokens[start - 1] if start > 0 else None
        if preceding in _TOPONYM_PREFIXES:
            continue
        return True
    return False


def _resolve_informazione_ente(*, hint: str | None) -> Ente | None:
    """Match a citizen-stated comune name against every ente TreasureIQ has
    an integration record for (`data/enti.json`), not only Albano.

    Unlike `_resolve_comune` (used on the AGEVOLAZIONE rail, where a wrong
    match could feed a residency criterion an unearned verdict), this rail
    never runs `match/engine.py` and only ever composes typed document/
    office/cost/diagnosis fields (D-19) — so naming a comune this chat has
    no eligibility seed for (e.g. Ariccia) is still safe to resolve.

    Matching is whole-token, not substring: `bare in needle` used to also
    fire on any hint that merely *contained* a short ente name as a
    fragment (e.g. a surname like "Marinoni"), and a naive word-boundary
    regex would still fire on "San Marino" as if the citizen meant the
    comune of Marino. Both are rejected here.

    Returns `None`, never a guess, when the hint is absent or matches
    nothing — the caller must treat `None` as "comune not established", and
    must NOT substitute Albano as if the citizen had said it (R-9): failing
    to resolve is a safe, cautious outcome; resolving wrongly is a
    confident, false one.
    """
    if not hint:
        return None
    tokens = re.findall(r"[\w']+", hint.casefold())
    for ente in load_enti().values():
        full_name = tuple(_bare_ente_name(ente).casefold().split())
        sequences = (*_ENTE_ALIAS_TOKENS.get(ente.codice_istat, ()), full_name)
        if any(_match_token_sequence(tokens=tokens, sequence=seq) for seq in sequences if seq):
            return ente
    return None


def _websearch_query(*, topic: Topic, ente: Ente) -> str | None:
    """The deterministic query for the `M6_web_aperto` rung (D-28), or
    `None` when this topic has no query template — a topic without one
    simply never triggers a web lookup, it is never guessed."""
    fragment = WEBSEARCH_QUERY_FRAGMENTS.get(topic)
    if fragment is None:
        return None
    return f"{fragment} {_bare_ente_name(ente)}"


def _citizen_effort(
    *,
    document: DocumentAnswer | None,
    office: OfficeAnswer | None,
    web_results: list[WebResultAnswer],
) -> int:
    """D-29: a plain count of concrete residual actions left to the citizen
    — never estimated, never combined with `recovery_cost`. One action per
    unverified link to check, one for a document to read, one for an office
    actually reachable (a URP entry with neither phone nor email, like Fonte
    Nuova's, is not an action the citizen can take)."""
    effort = len(web_results)
    if document is not None:
        effort += 1
    if office is not None and (office.telefono or office.email):
        effort += 1
    return effort


def _compose_informazione_reply(
    *,
    document: DocumentAnswer | None,
    office: OfficeAnswer | None,
    coverage_count: int,
    diagnosis: list[str],
    integration_cost: list[str],
    web_results: list[WebResultAnswer],
) -> str:
    """Every sentence here is composed from typed fields (D-24): there is no
    verbalisation step on this rail at all, so the D-24 invariant — no cost
    or diagnosis sentence ever reaches a model — holds by construction, not
    by discipline at a call site.
    """
    parts: list[str] = []
    if document is not None:
        parts.append(
            f"Ho trovato un documento su questo argomento: {document.title} — "
            f"{document.url}."
        )
    elif coverage_count == 0 and not web_results:
        parts.append("Il Comune non ha pubblicato un documento specifico su questo argomento.")
    if office is not None:
        contatti = ", ".join(v for v in (office.telefono, office.email) if v)
        if contatti:
            parts.append(f"Puoi rivolgerti a {office.nome} ({contatti}).")
        else:
            parts.append(f"Puoi rivolgerti a {office.nome}, che non pubblica un recapito diretto.")
    parts.extend(diagnosis)
    parts.extend(integration_cost)
    if web_results:
        parts.append(
            "Non risulta una fonte istituzionale per questo dato; ho trovato questi "
            "risultati sul web aperto, non verificati:"
        )
        parts.extend(f"- {result.title}: {result.url}" for result in web_results)
    return " ".join(parts)


async def _build_informazione_answer(
    *, intent: ChatIntent, records: list[Opportunity], comune_istat: str | None = None
) -> ChatAnswer:
    """The INFORMAZIONE rail (D-19): document + office + coverage + cost,
    never a verdict, never criteria, never SPID. No call into
    `match/engine.py` anywhere in this function.

    Three distinct outcomes for the comune, none of which silently
    substitutes Albano for an unconfirmed one (R-9): the citizen named a
    comune this chat recognises (proceed below); the citizen named one it
    does not recognise (say so, point at their own URP, offer nothing
    Albano-specific); or the citizen named none at all (ask, rather than
    presenting Albano's own office/cost as if it were theirs).
    """
    ente = _resolve_informazione_ente(hint=intent.comune_hint)

    if intent.topic in AMBIGUOUS_ROLE_TOPICS and intent.beneficiary_role is None:
        # This topic conflates two citizens under one word (D-19 round 2):
        # the answer a recipient needs and the answer a volunteer needs come
        # from different documents. A question we ask without using it is a
        # question for show — so this asks only for the topics where the
        # role actually changes `_search_opportunities`' keyword set (see
        # `AMBIGUOUS_ROLE_TOPICS`), never for every topic. Bundled with the
        # comune question in the same turn because this endpoint is
        # stateless and single-turn (D-09): there is no second chance to ask.
        return ChatAnswer(
            reply=(
                "Per rispondere con precisione mi servono due cose: il comune a cui ti "
                "riferisci e se questo servizio è per te o se vuoi offrirti come "
                "volontario per aiutare altre persone."
            ),
            topic=intent.topic,
            kind=QuestionKind.INFORMAZIONE,
            data_gap=None,
            needs_clarification=True,
            matches=[],
            spid_required=False,
            spid_reason=None,
            access_mode=None,
            citizen_effort=0,
            info=None,
        )

    if ente is None and not intent.comune_hint:
        return ChatAnswer(
            reply=(
                "Per rispondere con precisione mi serve sapere il tuo comune di "
                "residenza: a quale comune ti riferisci?"
            ),
            topic=intent.topic,
            kind=QuestionKind.INFORMAZIONE,
            data_gap=None,
            needs_clarification=True,
            matches=[],
            spid_required=False,
            spid_reason=None,
            access_mode=None,
            citizen_effort=0,
            info=None,
        )

    if ente is None:
        # D-32: fuori copertura si legge dal vivo il portale del comune stesso,
        # prima di rifiutare. Il rifiuto resta la risposta giusta solo finché
        # non ne esiste una migliore, e per un comune che ISTAT e IPA
        # conoscono ne esiste una migliore.
        live = await _risposta_live(
            hint=intent.comune_hint, topic=intent.topic, comune_istat=comune_istat
        )
        if live is not None:
            return live
        return ChatAnswer(
            reply=(
                f"Il comune che hai indicato ({intent.comune_hint}) non è tra quelli "
                "che questo sistema conosce: non posso verificarne l'ufficio o i dati. "
                "Contatta direttamente l'URP del tuo comune per questa informazione."
            ),
            topic=intent.topic,
            kind=QuestionKind.INFORMAZIONE,
            data_gap="comune_sconosciuto",
            needs_clarification=False,
            matches=[],
            spid_required=False,
            spid_reason=None,
            access_mode=None,
            citizen_effort=1,
            info=None,
        )

    candidates = (
        _search_opportunities(
            records=records, topic=intent.topic, role=intent.beneficiary_role
        )
        if ente.codice_istat == DEFAULT_COMUNE_ISTAT
        else []
    )
    document = (
        DocumentAnswer(title=candidates[0].title, url=str(candidates[0].source.url))
        if candidates
        else None
    )
    office = (
        OfficeAnswer(
            nome=ente.urp.nome,
            telefono=ente.urp.telefono,
            email=ente.urp.email,
            orari=ente.urp.orari,
        )
        if ente.urp is not None
        else None
    )
    diagnosis = diagnosis_lines(ente)
    integration_cost = cost_lines(ente)

    web_results: list[WebResultAnswer] = []
    access_mode = ente.access_mode.value
    institutional_exhausted = not candidates and ente.access_mode in (
        AccessMode.M4_CONNETTORE,
        AccessMode.M5_NESSUNO,
    )
    if institutional_exhausted:
        query = _websearch_query(topic=intent.topic, ente=ente)
        if query is not None:
            entry = load_websearch(query)
            if entry is not None and entry.results:
                web_results = [
                    WebResultAnswer(title=result.title, url=result.url)
                    for result in entry.results[:MAX_WEB_RESULTS_IN_REPLY]
                ]
                access_mode = AccessMode.M6_WEB_APERTO.value

    coverage_count = len(candidates)
    reply = _compose_informazione_reply(
        document=document,
        office=office,
        coverage_count=coverage_count,
        diagnosis=diagnosis,
        integration_cost=integration_cost,
        web_results=web_results,
    )

    return ChatAnswer(
        reply=reply,
        topic=intent.topic,
        kind=QuestionKind.INFORMAZIONE,
        data_gap=None if (document is not None or web_results) else "not_published",
        needs_clarification=False,
        matches=[],
        spid_required=False,
        spid_reason=None,
        access_mode=access_mode,
        citizen_effort=_citizen_effort(document=document, office=office, web_results=web_results),
        info=InfoAnswer(
            document=document,
            office=office,
            coverage_count=coverage_count,
            diagnosis=diagnosis,
            integration_cost=integration_cost,
            web_results=web_results,
        ),
    )


async def _risposta_live(
    *, hint: str | None, topic: Topic, comune_istat: str | None = None
) -> ChatAnswer | None:
    """Il gradino 2 (D-32): leggere ora il portale di un comune fuori copertura.

    `None` quando non c'è un comune italiano riconoscibile dietro l'accenno,
    e allora chi chiama tiene il proprio rifiuto: questa funzione aggiunge una
    risposta dove non ce n'era, non ne sostituisce una corretta.

    La sonda è HTTP sincrono e qui siamo dentro l'event loop, quindi gira su
    un thread: sei secondi di attesa bloccante fermerebbero ogni altra
    richiesta dell'API, non solo questa.
    """
    # Il codice scelto vale più del nome che se ne ricava. Ripartire dal nome
    # rimetteva in gioco l'ambiguità che la scelta serve a togliere: scelto
    # «Castro (LE)» dalla tendina, `risolvi_comune("Castro")` trovava due
    # comuni, rinunciava, e il cittadino si vedeva il vecchio rifiuto — con la
    # sua scelta esplicita già in mano al sistema.
    comune = comune_per_codice(comune_istat) or risolvi_comune(hint)
    if comune is None:
        return None

    try:
        letto = await asyncio.to_thread(leggi_orari_urp, comune)
    except Exception as exc:  # noqa: BLE001 — la rete che cade non è un 500
        logger.warning("sonda live fallita per %s: %s", comune.nome, exc)
        letto = None

    diagnosi = [
        f"{comune.nome} ({comune.provincia}) non è fra i comuni di cui abbiamo "
        "letto e verificato i dati: qui sotto c'è quello che il suo portale "
        "dice di sé, letto in questo momento.",
    ]
    if comune.sito:
        diagnosi.append(f"Portale istituzionale: {comune.sito} (fonte: IPA).")

    if comune.sito is None:
        # ISTAT sa che questo comune esiste, IPA non ci dà il suo sito: sono
        # 29 casi, fra cui Roma, che il registro chiama "Roma Capitale" e non
        # "Comune di Roma". Non è un portale che non risponde — è un indirizzo
        # che non abbiamo. Confondere le due cose direbbe al cittadino che il
        # suo comune è irraggiungibile quando il problema è nostro (D-35).
        return _chat_live(
            reply=(
                f"{comune.nome} esiste e lo riconosco ({comune.provincia}, codice "
                f"{comune.codice_istat}), ma nell'indice delle pubbliche "
                "amministrazioni non risulta l'indirizzo del suo portale, quindi non "
                "ho un posto dove andare a leggere. È un buco nostro, non suo."
            ),
            topic=topic,
            diagnosi=diagnosi,
            comune_sito=None,
            data_gap="not_published",
            citizen_effort=3,
        )

    if letto is None or letto.indirizzabilita is Indirizzabilita.IRRAGGIUNGIBILE:
        return _chat_live(
            reply=(
                f"{comune.nome} non è fra i comuni che abbiamo già letto, e in questo "
                "momento il suo portale non risponde. Non posso dirti nulla sui suoi "
                "uffici senza inventarmelo."
            ),
            topic=topic,
            diagnosi=diagnosi,
            comune_sito=comune.sito,
            data_gap="not_published",
            citizen_effort=2,
        )

    if letto.ha_orari:
        return _chat_live(
            reply=(
                f"{comune.nome} non è fra i comuni di cui abbiamo i dati, così sono "
                f"andato a leggere il suo portale adesso. Alla voce «{letto.ufficio}» "
                f"c'è scritto: «{letto.citazione}». È la pagina del comune, riportata "
                "alla lettera — non l'abbiamo verificata né messa nei nostri dati."
            ),
            topic=topic,
            diagnosi=diagnosi,
            comune_sito=comune.sito,
            ufficio=letto.ufficio,
            orari=letto.citazione,
            ufficio_url=letto.ufficio_url,
            access_mode=AccessMode.M2_PROSA_API.value,
            citizen_effort=1,
        )

    if letto.indirizzabilita is Indirizzabilita.API_UFFICI:
        coda = (
            f"L'ufficio «{letto.ufficio}» c'è, ma la sua pagina non pubblica un orario."
            if letto.ufficio
            else "Fra gli uffici pubblicati non ce n'è uno riconoscibile come URP."
        )
        return _chat_live(
            reply=(
                f"{comune.nome} pubblica l'elenco dei propri uffici in una forma "
                f"leggibile, e l'ho letto adesso. {coda} Per l'orario conviene "
                "chiamare o scrivere al comune."
            ),
            topic=topic,
            diagnosi=diagnosi,
            comune_sito=comune.sito,
            ufficio=letto.ufficio,
            ufficio_url=letto.ufficio_url,
            access_mode=AccessMode.M2_PROSA_API.value,
            data_gap="not_published",
            citizen_effort=2,
        )

    return _chat_live(
        reply=(
            f"{comune.nome} ha un portale, ma non espone i propri uffici in una forma "
            "che si possa leggere da qui: per sapere l'orario bisogna aprire il sito e "
            "cercarlo a mano. È il motivo per cui questo comune non è ancora fra quelli "
            "che copriamo."
        ),
        topic=topic,
        diagnosi=diagnosi,
        comune_sito=comune.sito,
        access_mode=AccessMode.M4_CONNETTORE.value,
        data_gap="not_published",
        citizen_effort=3,
    )


def _chat_live(
    *,
    reply: str,
    topic: Topic,
    diagnosi: list[str],
    comune_sito: str | None,
    ufficio: str | None = None,
    ufficio_url: str | None = None,
    orari: str | None = None,
    access_mode: str | None = None,
    data_gap: str | None = None,
    citizen_effort: int = 2,
) -> ChatAnswer:
    """Confeziona una risposta live come INFORMAZIONE, mai come verdetto.

    `matches` resta vuoto e `spid_required` falso per costruzione: niente di
    letto dal vivo può diventare un giudizio di eleggibilità (D-01/D-32).
    """
    documento = (
        DocumentAnswer(title=f"{ufficio} — pagina del comune", url=ufficio_url)
        if ufficio and ufficio_url
        else None
    )
    return ChatAnswer(
        reply=reply,
        topic=topic,
        kind=QuestionKind.INFORMAZIONE,
        data_gap=data_gap,
        needs_clarification=False,
        matches=[],
        spid_required=False,
        spid_reason=None,
        access_mode=access_mode,
        citizen_effort=citizen_effort,
        info=InfoAnswer(
            document=documento,
            office=(
                OfficeAnswer(nome=ufficio, telefono=None, email=None, orari=orari)
                if ufficio
                else None
            ),
            coverage_count=0,
            diagnosis=diagnosi,
            letto_dal_vivo=True,
            integration_cost=[
                "Lettura dal vivo, non un dato ingerito: nessuno snapshot di questo "
                "comune è stato salvato e nulla di quanto sopra entra nei dati del "
                "progetto finché non viene verificato."
            ],
            web_results=[],
        ),
    )


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
    storia: list[str] | None = None,
    comune_istat: str | None = None,
    today: date | None = None,
) -> ChatAnswer:
    """Answer one citizen turn. Never raises for model unavailability.

    `records` is the full, already-loaded set of opportunities for the
    citizen's comune (Albano, currently the only one with data) — this
    function only filters and evaluates, it never fetches.

    `storia` is the citizen's own earlier messages, oldest first. Without it
    every turn started from nothing: asked "dove si trova l'ufficio anagrafe",
    told "sono di Albano Laziale", and then asked "quali sono gli orari", the
    chat asked which comune a second time and had lost the subject as well.
    Only the citizen's own words are carried — never our replies, which would
    let one answer become the input to the next.
    """
    provider: LLMProvider = load_provider(role="chat")
    intent = await extract_intent(message=message, provider=provider)

    # Il comune non è un campo che convenga chiedere a un modello: l'elenco è
    # chiuso, pubblico e lo abbiamo su disco. Tre vie, in ordine di certezza.
    #
    # 1. Il cittadino l'ha SCELTO da una lista: c'è un codice ISTAT, e non si
    #    guarda nient'altro. Niente omonimi, niente grafie, niente modello.
    # 2. `_confirm_comune_hint` ha lasciato passare un accenno perché le sue
    #    parole erano davvero nella frase (R-9).
    # 3. Nessuna delle due: si legge la frase contro i 7.896 comuni italiani.
    #    `risolvi_comune` risponde solo se un nome compare davvero ed è uno
    #    solo, quindi non può reintrodurre ciò che la guardia ha scartato.
    scelto = comune_per_codice(comune_istat)
    if scelto is not None:
        intent = intent.model_copy(update={"comune_hint": scelto.nome})
    elif not (intent.comune_hint or "").strip():
        dedotto = risolvi_comune(message)
        if dedotto is not None:
            intent = intent.model_copy(update={"comune_hint": dedotto.nome})

    intent = _backfill_ambiguous_topic(intent=intent)
    intent = await _eredita_dal_contesto(
        intent=intent, messaggio=message, storia=storia or [], provider=provider
    )

    # R-8/D-19: `_backfill_ambiguous_topic` can restore a topic (VOLONTARIATO,
    # RIFIUTI) that `extract_intent` classified as SCONOSCIUTO and therefore
    # never saw the informational override for. Re-assert it here so an
    # informational-by-nature topic can never fall through to the engine and
    # produce a verdict, whatever `kind` the model emitted on the bare reply.
    if intent.topic in INFORMATIONAL_BY_NATURE_TOPICS:
        intent = intent.model_copy(update={"kind": QuestionKind.INFORMAZIONE})

    if intent.topic is Topic.SCONOSCIUTO:
        return ChatAnswer(
            reply=(
                "Non sono riuscito a collegare la tua richiesta a un servizio del "
                "Comune di Albano Laziale. Puoi provare a riformularla, oppure "
                "rivolgerti direttamente all'URP del Comune per essere indirizzato "
                "all'ufficio competente."
            ),
            topic=intent.topic,
            kind=intent.kind,
            data_gap="none_found",
            needs_clarification=True,
            matches=[],
            spid_required=False,
            spid_reason=None,
        )

    if intent.kind is QuestionKind.INFORMAZIONE:
        return await _build_informazione_answer(
            intent=intent, records=records, comune_istat=comune_istat
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
            kind=QuestionKind.AGEVOLAZIONE,
            data_gap="not_published",
            needs_clarification=False,
            matches=[],
            spid_required=False,
            spid_reason=None,
        )

    # Always evaluate every candidate (`include_ineligible=True`): the citizen
    # still deserves to know *why* they don't qualify, per `match.engine`'s
    # own design.
    #
    # Ineligible results are kept in the answer rather than filtered out. They
    # already sort last (`match` orders by verdict first), so they never
    # displace something the citizen can actually use — but dropping them
    # produced the worst answer this rail can give: asked about a high
    # electricity bill, a family whose ISEE sat just over the bonus ceiling was
    # shown a waste-collection service and never told the bonus existed. The
    # one relevant record had been silently removed for being a "no". A no with
    # a reason is an answer; substituting an unrelated yes is not.
    #
    # Filtering only when *every* candidate is ineligible, as this did before,
    # is the same bug with a narrower trigger: it needs just one irrelevant
    # survivor to hide the relevant refusal.
    results = match(candidates, active_profile, today=today, include_ineligible=True)

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
            kind=QuestionKind.AGEVOLAZIONE,
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
            kind=QuestionKind.AGEVOLAZIONE,
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
            reply=_apertura(results=top),
            topic=intent.topic,
            kind=QuestionKind.AGEVOLAZIONE,
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

    reply = _apertura(results=top)

    return ChatAnswer(
        reply=reply,
        topic=intent.topic,
        kind=QuestionKind.AGEVOLAZIONE,
        data_gap=None,
        needs_clarification=False,
        matches=top,
        spid_required=spid_required,
        spid_reason=spid_reason,
    )
