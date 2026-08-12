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
import threading
from functools import lru_cache
from dataclasses import dataclass, replace, field
from datetime import date, datetime, timezone
from enum import Enum
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
    _sesso_dichiarato_nel_testo,
    extract_intent,
)
from treasureiq.chat.categorie import Categoria, topics_di
from treasureiq.chat.nomi_genere import sesso_da_nome
from treasureiq.extract.providers import LLMProvider, load_provider
# Import del MODULO, non della funzione: i test mockano
# `treasureiq.bandi_live.bandi_arricchiti` con `mock.patch`, che sostituisce
# l'attributo sul modulo — un `from ... import bandi_arricchiti` legherebbe
# qui un nome che il patch non raggiungerebbe piu'.
from treasureiq import bandi_live
from treasureiq.bandi_live import BandiLiveEsito, BandoArricchito
# Stessa ragione del commento sopra (B4): i test mockano
# `treasureiq.connettore.leggi_connettore` con `mock.patch`.
from treasureiq import connettore
from treasureiq.connettore import UfficioConnettore
from treasureiq.orari_ufficio import leggi_orari_ufficio
from treasureiq.integration import (
    AccessMode,
    Ente,
    cost_lines,
    diagnosis_lines,
    load_enti,
    load_websearch,
)
from treasureiq.ingest.censimento import Indirizzabilita
from treasureiq.ingest.websearch import WebSearchNonConfigurato, entro_ttl, search_web
from treasureiq.sonda_live import (
    comune_per_codice,
    leggi_orari_urp,
    recupera_contatti,
    risolvi_comune,
    sonda_connettore,
)
from treasureiq.scansioni import aggiorna_scansione, carica_scansione, scansione_stantia
from treasureiq.match.engine import (
    CriterionState,
    MatchResult,
    Verdict,
    match,
    summarise,
)
from treasureiq.integration import load_enti
from treasureiq.schema import CitizenProfile, EmploymentStatus, Livello, Opportunity, TargetGroup

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
    #: La descrizione che il comune stesso dà del servizio, una riga sola e
    #: mai riscritta. Aiuta più del dominio a capire se è la pagina giusta.
    descrizione: str | None = None
    #: Quando abbiamo letto questa pagina. Sta in fondo alla scheda e in
    #: piccolo: aumenta la fiducia solo se non pretende di essere la risposta.
    verificato_il: date | None = None


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


class StatoFonte(str, Enum):
    """Che cosa abbiamo trovato, non che cosa spetta al cittadino.

    Sul rail INFORMAZIONE non esiste un verdetto e non deve nascerne uno
    dalla porta di servizio (D-19): questi valori descrivono la **provenienza**
    del dato — da dove viene e quanto è completo — mai il diritto di qualcuno
    a ottenere qualcosa.
    """

    UFFICIALE = "ufficiale"
    """Pagina del sito del comune, letta da noi."""

    PARZIALE = "parziale"
    """Il comune pubblica qualcosa, ma non tutto ciò che serviva."""

    NON_VERIFICATO = "non_verificato"
    """Solo pagine trovate con una ricerca sul web (D-28)."""

    NON_PUBBLICATO = "non_pubblicato"
    """Cercato dove doveva essere, non c'è."""


class StatoProva(str, Enum):
    """Lo stato di una singola cosa che possiamo o non possiamo confermare."""

    CONFERMATO = "confermato"
    PARZIALE = "parziale"
    MANCANTE = "mancante"


@dataclass
class Prova:
    """Una riga di «cosa posso confermare».

    Ogni riga è un fatto sul dato, composto da campi tipizzati: mai una
    percentuale di affidabilità, che sarebbe un numero inventato con l'aria
    di una misura.
    """

    stato: StatoProva
    testo: str


@dataclass
class Azione:
    """Una cosa che il cittadino può fare adesso, con dove farla.

    Sostituisce «cosa resta da fare a te: 2 azioni», che contava senza dire
    cosa — un numero che non aiuta nessuno a fare il passo successivo.
    """

    testo: str
    url: str | None = None
    tipo: str = "apri"
    #: Perché farla, in una riga. Il titolo dell'azione e la sua spiegazione
    #: stavano in una frase sola («Chiama URP — Ufficio Relazioni con il
    #: Pubblico per sapere quali documenti servono»), che come link diventa
    #: una riga di prosa sottolineata invece che un pulsante.
    dettaglio: str | None = None
    #: L'etichetta del pulsante: «Apri», «Chiama», «Scrivi».
    etichetta: str = "Apri"


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
    #: Da dove viene il dato e quanto è completo — mai a chi spetta cosa.
    stato: StatoFonte = StatoFonte.NON_PUBBLICATO
    #: Le righe di «cosa posso confermare», in ordine di importanza.
    prove: list[Prova] = field(default_factory=list)
    #: I passi successivi, scritti per esteso invece che contati.
    azioni: list[Azione] = field(default_factory=list)
    #: Il nome dell'ente, per la scheda: l'interfaccia non deve ricavarlo
    #: dal testo della risposta.
    ente_nome: str | None = None


@dataclass
class Connettore:
    """Esito della sonda AgID su un comune FUORI copertura: a ricerca fatta,
    dice se il suo portale espone l'API uffici del modello AgID — cioe' se il
    connettore *potrebbe* leggerlo, non che l'abbiamo letto.

    Nasce da una domanda concreta: la mappatura (censimento) e' un campione
    per le statistiche, `enti.json` sono i comuni ingeriti a mano; per un
    comune qualunque, a ricerca, non sapevamo se fosse indirizzabile e si
    ripiegava in silenzio sulla sola ricerca web. Questa sonda lo dice, senza
    ingerire. `uffici` e' un conteggio strutturale dell'API, non una cifra di
    spettanza: non lo tocca il modello (guardia sui numeri intatta)."""

    indirizzabile: bool
    uffici: int
    rest_base: str | None


@dataclass
class NumeriUtili:
    """Recapiti del comune letti al volo dal portale, non su richiesta.

    Fuori copertura li recuperiamo comunque — un cittadino che chiede aiuto e
    si sente dire «rivolgiti all'URP» senza un numero non e' stato aiutato. Il
    record porta sempre la sua provenienza (`fonte_tipo` = come li abbiamo
    presi) e quando (`letto_il`): il pannello li mostra come «ultimo controllo»,
    mai come dato verificato. Le cifre non le tocca il modello, le legge una
    regex sul sito (guardia sui numeri)."""

    telefoni: list[str]
    email: list[str]
    pec: list[str]
    fonte: str | None
    #: Come li abbiamo presi: per ora sempre «scansione web» (scraping del
    #: portale). Quando un comune sara' letto dal connettore, diventera' quello.
    fonte_tipo: str
    #: ISO 8601, ora del recupero — il pannello lo rende come «ultimo controllo».
    letto_il: str


@dataclass
class ComuneAmbiguo:
    """Un candidato di disambiguazione, per la scheda cliccabile nella UI.

    Porta l'ISTAT cosi' che scegliere sia un tap: il frontend rimanda la stessa
    domanda con questo `codice_istat`, non fa ridigitare il nome al cittadino."""

    nome: str
    provincia: str
    codice_istat: str


@dataclass
class ScanStato:
    """Stato dello scan del comune riconosciuto, per il rail chat (D-S6).

    `stato` e' `"fresco"` (scan <6gg, servito dalla cache) o
    `"aggiornamento_in_corso"` (scan assente o stantio, refresh partito in
    background). `ultimo_scan` e' l'ISO-8601 del record in cache, `None` se
    non ne esiste ancora uno."""

    stato: str
    ultimo_scan: str | None


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
    connettore: Connettore | None = None
    numeri_utili: NumeriUtili | None = None
    comuni_ambigui: list[ComuneAmbiguo] | None = None
    scan: ScanStato | None = None
    #: Esito grezzo di `bandi_live.bandi_arricchiti`, topic BANDI soltanto.
    #: I criteri e le cifre di ogni bando (`Requirements`, importi, scadenze)
    #: viaggiano SOLO qui, mai interpolati in `reply`: il verbalizzatore non
    #: tocca mai questo campo (D-07, «il verbalizzatore corrompe le cifre»).
    bandi_live: BandiLiveEsito | None = None
    #: Esito grezzo di `connettore.leggi_connettore` (B4), ramo M4_CONNETTORE
    #: scattato. Recapiti/orari/AT strutturati e verbatim: la card del web
    #: (B5) li legge da qui, mai da `reply` (D-07). `None` quando il
    #: connettore non ha risposto o il ramo non e' scattato (A7).
    esito_connettore: connettore.EsitoConnettore | None = None
    #: Ciclo12/B1: quale slot di follow-up questo turno chiede (`None` =
    #: nessuno). Additivo: `reply` porta comunque la risposta di merito,
    #: la domanda si accoda (D-04, mai bloccante). Stesso enum chiuso di
    #: `ChatIn.chiarimento_atteso`/`ChatOut.chiarimento`.
    chiarimento: str | None = None


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


def _profile_from_slots(
    *,
    intent: ChatIntent,
    messaggio: str = "",
    filtri_esclusi: frozenset | None = None,
) -> CitizenProfile:
    """Build an anonymous profile from whatever the citizen volunteered.

    Ciclo11/D-05: `riconosci_filtri` (`treasureiq.chat.filtri`) is now the
    SOLE source of anagraphic slots — `intent.slots` is always an empty
    `ProfileSlots()` after D-01 (Ollama is no longer asked for them). Lazy
    import: `filtri.py` imports this module at module level, so this module
    can only import `filtri.py` back lazily, inside the function, to avoid a
    cycle.

    `filtri_esclusi` (A8, ciclo11): chiavi `FiltroChiave` che il cittadino ha
    chiesto di togliere dal ricalcolo (`ChatIn.filtri_override`) — un filtro
    letto correttamente dal testo ma che non lo riguarda ("non sono io il
    disabile, e' mia madre"). Semplice esclusione, mai una sostituzione
    indovinata (A12): la chiave torna a essere uno slot vuoto, non un valore
    diverso.

    Every field the citizen did not state is handed to the engine as a real
    `None` (R-9) — `CitizenProfile` and `match/engine.py` both accept that.
    """
    from treasureiq.chat.filtri import FiltroChiave, riconosci_filtri

    esclusi = filtri_esclusi or frozenset()
    filtri = {
        f.chiave: f.valore for f in riconosci_filtri(messaggio) if f.chiave not in esclusi
    }
    comune_istat, comune_nome = _resolve_comune(hint=intent.comune_hint)
    # D-52: il sesso resta FUORI dal catalogo `FiltroChiave` di proposito
    # (B2/brief): la dichiarazione esplicita ("sono una donna") vince sempre;
    # solo se il cittadino non l'ha detto si prova la deduzione dal nome
    # proprio, deterministica e fuori dal grammar del modello (vedi
    # `chat.nomi_genere`). Una deduzione resta comunque una deduzione: chi
    # mostra il profilo la marca correggibile, mai un filtro nascosto.
    sesso = _sesso_dichiarato_nel_testo(messaggio) or sesso_da_nome(messaggio)
    isee_valore = filtri.get(FiltroChiave.ISEE)
    employment_valore = filtri.get(FiltroChiave.EMPLOYMENT_STATUS)
    return CitizenProfile(
        comune_istat=comune_istat,
        comune_nome=comune_nome,
        eta=filtri.get(FiltroChiave.ETA),
        # `str(float)` round-trips exactly through `Decimal` for the plain
        # decimal ISEE figures a citizen would type; see `ProfileSlots.isee`
        # for why filtri.py carries `float`, not `Decimal`.
        isee=Decimal(str(isee_valore)) if isee_valore is not None else None,
        nucleo_familiare=filtri.get(FiltroChiave.NUCLEO_FAMILIARE),
        figli_minori=filtri.get(FiltroChiave.FIGLI_MINORI),
        disabilita=filtri.get(FiltroChiave.DISABILITA),
        sesso=sesso,
        # `FiltroChiave` non ha una chiave di CONTEGGIO figli disabili (solo
        # il booleano `disabilita_nucleo`) — riduzione onesta di scope
        # rispetto al vecchio `ProfileSlots.figli_disabili`, mai un numero
        # indovinato (A12/L-5).
        figli_disabili=None,
        disabilita_nucleo=filtri.get(FiltroChiave.DISABILITA_NUCLEO),
        employment_status=(
            EmploymentStatus(employment_valore) if employment_valore is not None else None
        ),
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


def _topic_da_storia(*, storia: list[str]) -> Topic | None:
    """Il topic implicato dalle parole che il cittadino ha scritto prima.

    D-47 hard rule: il topic non si eredita mai fidandosi solo del modello —
    nemmeno rilanciando `extract_intent` su un turno passato, perché quella
    è comunque una classificazione del modello, fatta una seconda volta. Qui
    si guarda solo se le parole del topic (lo stesso vocabolario chiuso di
    `TOPIC_KEYWORDS` che usa `_search_opportunities`) compaiono per davvero
    in un turno precedente — corroborato dalle parole, mai dedotto.

    Più recente per primo: l'ultima cosa detta vince, come nel parlato.
    """
    for passato in reversed(storia):
        haystack = passato.lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if keywords and _keyword_hit(haystack=haystack, keywords=keywords):
                return topic
    return None


async def _eredita_dal_contesto(
    *, intent: ChatIntent, messaggio: str, storia: list[str], provider: LLMProvider
) -> ChatIntent:
    """Carry forward the comune and the subject the citizen already gave.

    A turn that supplies only a comune ("sono di Albano Laziale") has no topic
    of its own, and a turn that supplies only a follow-up ("quali sono gli
    orari?") has no comune. Read in isolation each is unanswerable, and the
    chat was reading them in isolation — so it asked for the comune twice and
    lost the subject in between.

    The comune is recovered from the citizen's own earlier messages,
    re-extracted through the same closed schema rather than parsed here:
    whatever is inherited has to come from the same mechanism that would have
    accepted it when it was first said, or the two paths could disagree about
    what a sentence means. The topic is recovered differently (D-47 hard
    rule): never by trusting the model's classification of an old turn again,
    only by finding that topic's own keywords in what the citizen actually
    wrote — see `_topic_da_storia`.

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

    if serve_tema:
        ereditato = _topic_da_storia(storia=storia[-6:])
        if ereditato is not None:
            aggiornamenti["topic"] = ereditato
            serve_tema = False

    if serve_comune:
        # Most recent first: the last thing said wins, as it would in speech.
        for passato in reversed(storia[-6:]):
            try:
                vecchio = await extract_intent(message=passato, provider=provider)
            except Exception:  # noqa: BLE001 — a failed re-read is not fatal
                continue
            if vecchio.comune_hint:
                aggiornamenti["comune_hint"] = vecchio.comune_hint
                break

    return intent.model_copy(update=aggiornamenti) if aggiornamenti else intent


def _keywords_for(*, topic: Topic, role: BeneficiaryRole | None = None) -> tuple[str, ...]:
    """The keyword set that defines this topic, for retrieval and for judging
    a candidate's relevance alike. One source, so the two can never disagree
    on what the citizen asked about."""
    role_keywords = AMBIGUOUS_ROLE_TOPICS.get(topic, {}).get(role) if role is not None else None
    return role_keywords if role_keywords is not None else TOPIC_KEYWORDS.get(topic, ())


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
    keywords = _keywords_for(topic=topic, role=role)
    if not keywords:
        return []
    hits: list[Opportunity] = []
    for opportunity in records:
        haystack = " ".join(
            part for part in (opportunity.title, opportunity.summary, opportunity.body) if part
        ).lower()
        if _keyword_hit(haystack=haystack, keywords=keywords):
            hits.append(opportunity)
    return _senza_scadute(hits)


#: Sinonimi di "tutte le categorie" — parole intere, non radici: qui non
#: serve lo stemmer (D-55 propone tre nomi fissi più questo), e una radice
#: tronca allargherebbe il match a frasi che non stanno rispondendo a questa
#: domanda.
_PAROLE_TUTTE_CATEGORIE: tuple[str, ...] = ("tutte", "tutto", "qualsiasi", "ogni")

#: Numero massimo di parole perché un turno sia letto come risposta diretta
#: alla domanda categoria, non come una nuova domanda che nomina di
#: sfuggita "mezzi" o "assegni" dentro una frase vera.
_MAX_PAROLE_RISPOSTA_CATEGORIA = 6


def _slot_anagrafici_dichiarati(profile: CitizenProfile) -> int:
    """Quanti campi anagrafici il cittadino ha dichiarato (D-55: «profilo
    ricco» = almeno due). Non conta il comune, che è un dato di instradamento
    (D-09), non anagrafico."""
    campi = (
        profile.eta,
        profile.isee,
        profile.nucleo_familiare,
        profile.figli_minori,
        profile.disabilita,
        profile.sesso,
        profile.figli_disabili,
        profile.employment_status,
    )
    return sum(1 for campo in campi if campo is not None)


def _categoria_richiesta(message: str) -> "Categoria | str | None":
    """Se questo turno risponde alla domanda categoria di D-55 — «tutte» o
    il nome di una categoria — e in tal caso quale. `None` se il turno non è
    una risposta a quella domanda (o non c'è mai stata): una nuova domanda
    vera prosegue nel flusso a singolo topic, invariato.

    Letto sul testo del cittadino con lo stesso confine di parola di
    `_keyword_hit`, mai dalla classificazione del modello — «tutte» e i nomi
    delle categorie non sono nel vocabolario chiuso di `Topic`.
    """
    haystack = message.lower()
    if len(haystack.split()) > _MAX_PAROLE_RISPOSTA_CATEGORIA:
        return None
    if _keyword_hit(haystack=haystack, keywords=_PAROLE_TUTTE_CATEGORIE):
        return "tutte"
    for categoria in Categoria:
        if categoria is Categoria.ALTRO:
            # "altro" non è mai proposto come scelta in chat (D-55 elenca
            # solo utenze/mezzi/assegni), quindi non è mai una risposta.
            continue
        if _keyword_hit(haystack=haystack, keywords=(categoria.value,)):
            return categoria
    return None


def _senza_scadute(trovate: list[Opportunity]) -> list[Opportunity]:
    """Toglie le opportunità la cui scadenza è già passata.

    Un bando scaduto non è un'informazione incompleta: è un falso positivo che
    fa perdere tempo a chi ne ha meno. Una persona che legge «Voucher asilo
    nido 2025» non ha modo di sapere, dalla scheda, che il termine è passato
    otto mesi fa.

    Scadenza assente vuol dire due cose diverse — sempre aperto, oppure non
    pubblicata — e `Opportunity.is_expired` è falso in entrambi i casi: nel
    dubbio si mostra, perché nascondere qualcosa che potrebbe spettare è un
    danno peggiore che mostrare qualcosa di incerto.
    """
    vive = [o for o in trovate if not o.is_expired]
    # Chi ha un anno passato nel titolo va in fondo, non via.
    #
    # Il comune non ha pubblicato nessuna scadenza — `deadline` è `None` su
    # tutte e tre le schede che hanno prodotto questa regola — quindi dire che
    # sono chiuse sarebbe una deduzione nostra. Ma «Voucher asilo nido 2025»
    # in agosto 2026 non è una proposta seria da mettere per prima, e chi
    # legge quell'anno lo vede da sé.
    return sorted(vive, key=_anno_probabilmente_passato)


def _anno_probabilmente_passato(opportunity: Opportunity) -> int:
    """1 se il titolo porta un anno già finito, 0 altrimenti.

    Legge l'anno scritto, non lo indovina: è la differenza fra riferire ciò
    che il comune ha pubblicato e concludere qualcosa al posto suo.
    """
    anni = re.findall(r"\b(20\d{2})\b", opportunity.title or "")
    if not anni:
        return 0
    return 1 if max(int(a) for a in anni) < date.today().year else 0


def _keyword_hit(*, haystack: str, keywords: tuple[str, ...]) -> bool:
    """Whether any keyword occurs in `haystack`, as a word and not by accident.

    Una parola sola deve cominciare dove comincia una parola: "tari" dentro
    "sanitaria" e "tributi" dentro "contributi" sono coincidenze di lettere,
    non l'argomento chiesto — e questa funzione decide quale pagina finisce
    davanti al cittadino. Chiesto l'ufficio tributi, la chat rispondeva con
    l'erogazione dei contributi per i libri di testo.

    Le radici tronche, scritte per prendere ogni desinenza, finiscono con un
    trattino in `TOPIC_KEYWORDS` («disabilit-», «maternit-»): solo quelle
    rinunciano al confine di destra. Senza questa distinzione, o si perde
    «disabilità», o «tari» prende «tariffa» — e prendeva «tariffa», tanto che
    la domanda sull'ufficio tributi tornava con la raccolta dei pannolini.

    Le chiavi di più parole restano sottostringhe: una frase intera che
    ricorre per caso non è un rischio reale.

    In coda, e solo se nessun confronto letterale ha agganciato, si confrontano
    le **radici**: «asili nido» non conteneva la chiave «asilo», «agevolazioni»
    non conteneva «agevolazione», e il cittadino scrive al plurale molto più
    spesso di quanto scriva al singolare.

    La radice viene per ultima di proposito. Le distinzioni che questa funzione
    protegge sopravvivono — `tari`→`tar` resta diverso da `tariffa`→`tariff`,
    `tributi`→`trib` da `contributi`→`contrib` — ma un confronto più largo
    provato per primo renderebbe inutili le guardie scritte sopra.
    """
    for keyword in keywords:
        if " " in keyword:
            if keyword in haystack:
                return True
        elif keyword.endswith("-"):
            if re.search(rf"\b{re.escape(keyword[:-1])}", haystack):
                return True
        elif re.search(rf"\b{re.escape(keyword)}\b", haystack):
            return True
    return _radici_in_comune(haystack=haystack, keywords=keywords)


@lru_cache(maxsize=1)
def _stemmer():
    """Lo stemmer italiano, caricato una volta sola."""
    import snowballstemmer

    return snowballstemmer.stemmer("italian")


@lru_cache(maxsize=8192)
def _radice(parola: str) -> str:
    return _stemmer().stemWord(parola)


def _radici(testo: str) -> frozenset[str]:
    """Le radici delle parole di un testo, senza le troppo corte.

    Sotto le tre lettere una radice non distingue più niente: «di», «un» e
    «al» aggancerebbero qualunque cosa.
    """
    return frozenset(
        r for p in re.findall(r"\w+", testo.lower()) if len(r := _radice(p)) >= 3
    )


def _radici_in_comune(*, haystack: str, keywords: tuple[str, ...]) -> bool:
    """Confronto per radice, per le chiavi di una parola sola.

    Le chiavi di più parole e le radici già tronche restano fuori: le prime
    perché una frase va confrontata intera, le seconde perché sono già una
    radice scritta a mano, e stemmarne una troncata darebbe risultati che
    nessuno ha previsto.
    """
    semplici = [k for k in keywords if " " not in k and not k.endswith("-")]
    if not semplici:
        return False
    presenti = _radici(haystack)
    return any(_radice(k) in presenti for k in semplici)


def _parole_del_cittadino(*, message: str, storia: list[str]) -> str:
    """Il messaggio corrente più i precedenti del cittadino, in minuscolo."""
    return " ".join([*storia, message]).lower()


#: Parole che compaiono in qualunque domanda civica e in qualunque pagina
#: comunale. Contarle come punti di contatto significherebbe dichiarare
#: pertinente ogni pagina rispetto a ogni domanda.
_PAROLE_GENERICHE = frozenset(
    {
        "comune",
        "documenti",
        "informazioni",
        "orari",
        "pagina",
        "quali",
        "servizio",
        "servizi",
        "sportello",
        "ufficio",
        "uffici",
    }
)


def _parole_piene(testo: str) -> set[str]:
    """Le parole di contenuto di un testo: almeno quattro lettere, non
    generiche. Il taglio è grossolano di proposito — serve a dire se due testi
    parlano della stessa cosa, non a capirli."""
    return {
        parola
        for parola in re.findall(r"[a-zàèéìòù']{4,}", testo.lower())
        if parola not in _PAROLE_GENERICHE
    }


def _pertinente(
    *,
    topic: Topic,
    role: BeneficiaryRole | None,
    parole: str,
    candidato: Opportunity,
    ente: Ente | None = None,
) -> bool:
    """Whether a retrieved record is *about* what the citizen asked.

    `_search_opportunities` cerca anche nel corpo della pagina, ed è giusto che
    lo faccia: serve a trovare i candidati. Ma il corpo nomina di passaggio
    cose di cui la pagina non parla — la pagina dei pannolini chiede «copia
    dell'ultimo versamento TARI» fra i documenti da allegare, e tanto bastava
    perché una domanda sull'ufficio tributi ricevesse quella. L'argomento di
    una pagina sta nel titolo e nella sua descrizione; il corpo è contesto.

    Due vie, e basta una.

    La prima chiede due riscontri, non uno: le parole chiave del topic devono
    stare nella frase del cittadino *e* nel titolo della pagina. Il topic lo
    sceglie un modello, e un modello davanti a una domanda fuori catalogo non
    risponde «nessuna categoria»: risponde con la più vicina che esiste — e
    trova per quella una pagina perfettamente coerente. Chiesto l'ufficio
    tributi, ha proposto prima l'anagrafe e poi la raccolta differenziata: due
    pagine giuste sotto una domanda che non era la loro. Il riscontro sulle
    parole del cittadino è la stessa guardia già applicata al comune (R-9).

    La seconda via è il titolo che condivide una parola piena con quelle del
    cittadino: così una domanda posta con parole diverse da quelle del
    catalogo («dove butto la plastica») trova comunque la sua pagina.

    Si guardano anche i messaggi precedenti del cittadino, perché il topic può
    venire da quelli (`_eredita_dal_contesto`) — mai le nostre risposte, che
    renderebbero la guardia autoreferenziale.
    """
    titolo = f"{candidato.title} {candidato.summary or ''}".lower()
    keywords = _keywords_for(topic=topic, role=role)
    # Il nome del comune non è un argomento. Compare in quasi ogni pagina del
    # suo sito e in quasi ogni domanda posta per esteso: contarlo fra le
    # parole in comune rendeva pertinente qualunque pagina — «orari
    # dell'ufficio tributi di Albano Laziale» tornava con la raccolta
    # differenziata perché anche quella pagina dice «Albano Laziale».
    escluse = _parole_piene(_bare_ente_name(ente)) if ente is not None else set()
    if _keyword_hit(haystack=parole, keywords=keywords) and _keyword_hit(
        haystack=titolo, keywords=keywords
    ):
        return True
    return bool((_parole_piene(parole) - escluse) & (_parole_piene(titolo) - escluse))


def _document_answer(candidato: Opportunity) -> DocumentAnswer:
    """La scheda del servizio come la pubblica il comune, mai riscritta."""
    sommario = (candidato.summary or "").strip()
    return DocumentAnswer(
        title=candidato.title,
        url=str(candidato.source.url),
        descrizione=sommario or None,
        verificato_il=candidato.source.fetched_at.date()
        if candidato.source.fetched_at is not None
        else None,
    )


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


#: Parole che seguono "ufficio" senza nominarne uno: "ufficio competente" non
#: è un ufficio, è un modo di dire.
_UFFICIO_GENERICO = frozenset({"comunale", "competente", "comune", "giusto", "preposto"})


def _ufficio_chiesto(parole: str) -> str | None:
    """L'ufficio che il cittadino ha nominato, se ne ha nominato uno.

    Serve a non spacciare per suoi gli orari di un altro ufficio: chiesto
    l'ufficio tributi, la scheda mostrava gli orari dell'URP senza dire che
    erano quelli dell'URP — un dato giusto sotto la domanda sbagliata, che è
    il modo più efficace di mandare qualcuno davanti a una porta chiusa.
    """
    trovati = re.findall(r"uffici[oi]\s+(?:di\s+|del\s+|delle?\s+)?([a-zàèéìòù']{3,})", parole)
    for nome in trovati:
        if nome not in _UFFICIO_GENERICO:
            return nome
    return None


def _disabilita_attiva_nel_testo(parole: str) -> bool:
    """Il filtro disabilita (proprio o del nucleo) e' acceso in questo testo?

    Stessa fonte unica di `_profile_from_slots` (`riconosci_filtri`, D-05):
    mai un pattern-match parallelo sul messaggio. Lazy import per lo stesso
    ciclo di `_profile_from_slots`: `filtri.py` importa questo modulo a
    livello di modulo, quindi qui si puo' importare `filtri.py` solo dentro
    la funzione (ciclo11 B5, A9).
    """
    from treasureiq.chat.filtri import FiltroChiave, riconosci_filtri

    chiavi = {f.chiave for f in riconosci_filtri(parole)}
    return FiltroChiave.DISABILITA in chiavi or FiltroChiave.DISABILITA_NUCLEO in chiavi


def _prove_e_stato(
    *,
    document: DocumentAnswer | None,
    office: OfficeAnswer | None,
    web_results: list[WebResultAnswer],
    letto_dal_vivo: bool,
    ufficio_chiesto: str | None = None,
) -> tuple[StatoFonte, list[Prova]]:
    """«Cosa posso confermare», composto dai campi e da nient'altro.

    Ogni riga è un fatto verificabile sul dato — da dove viene, cosa contiene,
    cosa gli manca — mai una percentuale di affidabilità: un numero del genere
    avrebbe l'aria di una misura senza esserlo, ed è esattamente il tipo di
    finta precisione che questo progetto esiste per non produrre.

    Le assenze si dichiarano (D-35): «i requisiti non risultano pubblicati» è
    una riga come le altre, non una riga che manca.
    """
    prove: list[Prova] = []

    if document is not None:
        prove.append(
            Prova(
                StatoProva.CONFERMATO,
                "La pagina viene dal sito ufficiale del comune",
            )
        )
    elif web_results:
        prove.append(
            Prova(
                StatoProva.PARZIALE,
                "Queste pagine vengono da una ricerca sul web, non da una fonte "
                "che abbiamo letto",
            )
        )
    else:
        prove.append(
            Prova(StatoProva.MANCANTE, "Il comune non pubblica una pagina su questo argomento")
        )

    if letto_dal_vivo:
        prove.append(
            Prova(
                StatoProva.PARZIALE,
                "Letto ora dal portale del comune: verbatim dalla fonte, non "
                "verificato da noi",
            )
        )

    if office is not None:
        recapiti = [v for v in (office.telefono, office.email) if v]
        if recapiti:
            prove.append(
                Prova(StatoProva.CONFERMATO, "Sono disponibili i contatti dell'ufficio competente")
            )
        else:
            prove.append(
                # Ciclo 15 R2: non «l'ufficio non pubblica» (falso — spesso il
                # recapito e' nella pagina HTML). Il connettore legge solo i dati
                # in formato aperto: cio' che sta solo nella pagina non lo legge.
                Prova(StatoProva.MANCANTE, "Un recapito diretto non è tra i dati aperti letti dal connettore")
            )
        if not office.orari:
            prove.append(
                Prova(StatoProva.MANCANTE, "Gli orari non sono tra i dati aperti letti dal connettore")
            )
        elif ufficio_chiesto and ufficio_chiesto not in office.nome.lower():
            prove.append(
                Prova(
                    StatoProva.MANCANTE,
                    f"Gli orari dell'ufficio {ufficio_chiesto} non risultano "
                    f"pubblicati: quelli qui sotto sono di {office.nome}",
                )
            )
    else:
        prove.append(
            Prova(StatoProva.MANCANTE, "Il comune non pubblica un ufficio di riferimento")
        )

    if document is not None and any(p.stato is StatoProva.MANCANTE for p in prove):
        stato = StatoFonte.PARZIALE
    elif document is not None:
        stato = StatoFonte.UFFICIALE
    elif web_results:
        stato = StatoFonte.NON_VERIFICATO
    else:
        stato = StatoFonte.NON_PUBBLICATO
    return stato, prove


def _azioni_possibili(
    *,
    document: DocumentAnswer | None,
    office: OfficeAnswer | None,
    web_results: list[WebResultAnswer],
) -> list[Azione]:
    """I passi successivi, scritti e non contati.

    Al massimo tre: una lista più lunga smette di essere un consiglio e
    diventa un modulo da compilare.
    """
    azioni: list[Azione] = []
    if document is not None:
        azioni.append(
            Azione(
                "Consulta il servizio",
                document.url,
                "apri",
                dettaglio="Apri la pagina ufficiale del comune",
                etichetta="Apri",
            )
        )
    elif web_results:
        azioni.append(
            Azione(
                "Controlla la pagina trovata",
                web_results[0].url,
                "apri",
                dettaglio="Non l'abbiamo verificata: guarda che sia del tuo comune",
                etichetta="Apri",
            )
        )

    if office is not None:
        if office.telefono:
            azioni.append(
                Azione(
                    "Verifica i documenti necessari",
                    f"tel:{office.telefono.replace(' ', '')}",
                    "chiama",
                    dettaglio=f"Contatta {office.nome} prima di presentare la richiesta",
                    etichetta="Chiama",
                )
            )
        elif office.email:
            azioni.append(
                Azione(
                    "Verifica i documenti necessari",
                    f"mailto:{office.email}",
                    "email",
                    dettaglio=f"Scrivi a {office.nome} prima di presentare la richiesta",
                    etichetta="Scrivi",
                )
            )

    if not azioni:
        azioni.append(
            Azione(
                "Contatta l'URP del tuo comune",
                dettaglio="Da qui non risulta pubblicato nulla su questo argomento",
            )
        )
    return azioni[:3]


def _compose_informazione_reply(
    *,
    ente_nome: str,
    document: DocumentAnswer | None,
    web_results: list[WebResultAnswer],
) -> str:
    """La frase di apertura, e nient'altro.

    Componeva anche il documento col suo URL, i recapiti dell'ufficio, la
    diagnosi del portale e il costo d'integrazione — tutti campi che
    l'interfaccia riceve già tipizzati in `InfoAnswer` e rende per conto suo.
    Il risultato era che ogni risposta diceva le stesse cose due volte: una
    volta impastate in un paragrafo e una volta in blocchi, con dentro
    `M2_prosa_api` e `/wp-json/wp/v2/types` in mezzo a un discorso rivolto a
    un cittadino.

    Ora la prosa risponde alla domanda e si ferma. Tutto il resto è nei campi,
    dove l'interfaccia può dargli il peso che merita — e il tecnico può
    starsene chiuso finché qualcuno non lo apre.

    Resta composta da campi tipizzati (D-24): su questo rail non esiste alcun
    passaggio di verbalizzazione, quindi l'invariante regge per costruzione.
    """
    if document is not None:
        # La prima riga deve già rispondere, non annunciare che una risposta
        # esiste: «ho trovato una pagina su questo argomento» costringe a
        # leggere la scheda per sapere di cosa parla. Il titolo del servizio è
        # del comune e va riportato tale e quale — riformularlo qui sarebbe
        # verbalizzazione, che su questo rail non esiste (D-24).
        return f"Il {ente_nome} pubblica un servizio ufficiale: «{document.title}»."
    if web_results:
        return (
            f"{ente_nome}: non ho trovato una fonte istituzionale su questo argomento. "
            "Queste pagine vengono da una ricerca sul web e non le ho verificate."
        )
    return (
        f"{ente_nome} non ha pubblicato niente su questo argomento in una forma che "
        "io possa leggere. Qui sotto c'è l'ufficio a cui chiederlo."
    )


async def _build_informazione_answer(
    *,
    intent: ChatIntent,
    records: list[Opportunity],
    comune_istat: str | None = None,
    parole: str = "",
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
            hint=intent.comune_hint,
            topic=intent.topic,
            comune_istat=comune_istat,
            parole=parole,
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

    # Il topic del modello vale solo se le parole del cittadino lo reggono
    # (`_riscontro_lessicale`). Senza questa condizione una domanda fuori
    # catalogo — l'ufficio tributi — riceveva la pagina del topic più vicino
    # che il catalogo copre, l'anagrafe, presentata come la risposta.
    trovati = (
        _search_opportunities(
            records=records, topic=intent.topic, role=intent.beneficiary_role
        )
        if ente.codice_istat == DEFAULT_COMUNE_ISTAT
        else []
    )
    candidates = [
        c
        for c in trovati
        if _pertinente(
            topic=intent.topic,
            role=intent.beneficiary_role,
            parole=parole,
            candidato=c,
            ente=ente,
        )
    ]
    document = _document_answer(candidates[0]) if candidates else None
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
    # Fix on-demand orari-ufficio (ciclo18c): l'`office` qui sopra è l'URP di
    # ripiego. Se il cittadino ha nominato un ufficio preciso («anagrafe»), il
    # connettore ne conosce già la URL (catalogata dallo sweep): la si legge
    # adesso e si cita il SUO orario, invece di quello dell'URP. Vale anche con
    # un servizio già in match (`candidates` non vuoto): lì il ramo connettore
    # più sotto non gira, e l'URP resterebbe l'unica scheda. Solo rail
    # INFORMAZIONE, nessun verdetto; degrado onesto se la pagina non pubblica
    # orari (D-32) — l'ufficio giusto con `orari=None`, mai l'URP travestito.
    ufficio_nominato = _ufficio_chiesto(parole)
    if ufficio_nominato is not None:
        office_ufficio = await _office_da_ufficio_nominato(
            codice_istat=ente.codice_istat,
            topic=intent.topic,
            ufficio_chiesto=ufficio_nominato,
            disabilita_attiva=_disabilita_attiva_nel_testo(parole),
        )
        if office_ufficio is not None:
            office = office_ufficio
    diagnosis = diagnosis_lines(ente)
    integration_cost = cost_lines(ente)

    web_results: list[WebResultAnswer] = []
    access_mode = ente.access_mode.value

    # M4-servito vs M4/M5-gap (B4): un ente censito NON è per forza esausto —
    # proviamo il connettore per davvero prima di trattarlo come il gap che
    # l'`access_mode` MISURATO descrive. Vale anche per M5_NESSUNO: quel campo
    # è statico e fu classificato PRIMA che la famiglia di piattaforma avesse
    # un connettore (es. eGov Marino, 58 uffici leggibili, marcato M5 in
    # `enti.json`). L'`access_mode` congelato non deve decidere il routing
    # quando il connettore, chiesto, legge dati veri: predicato vecchio cieco
    # al connettore nuovo. Se il connettore legge, questo intercetta la
    # risposta qui e non attraversa mai il ramo institutional_exhausted sotto
    # (niente sonda, niente ricerca web, niente falso «non ha pubblicato
    # niente»). Se il connettore non ha nulla (`None` o degradato-vuoto), il
    # flusso prosegue ESATTAMENTE come prima — institutional_exhausted (che
    # già include M4+M5) resta vero e nulla cambia per gli altri comuni (A7).
    # `leggi_connettore` è cache-first: un comune già scansionato risponde
    # dallo store senza rete; solo un M5 freddo paga un GET alla home in più.
    if not candidates and ente.access_mode in (
        AccessMode.M4_CONNETTORE,
        AccessMode.M5_NESSUNO,
    ):
        esito_connettore = await asyncio.to_thread(connettore.leggi_connettore, ente.codice_istat)
        if esito_connettore is not None and (
            esito_connettore.uffici or esito_connettore.amministrazione_trasparente is not None
        ):
            risposta_connettore = await _risposta_da_connettore(
                comune_nome=ente.ente,
                topic=intent.topic,
                diagnosi=diagnosis,
                esito=esito_connettore,
                ufficio_chiesto=_ufficio_chiesto(parole),
                disabilita_attiva=_disabilita_attiva_nel_testo(parole),
            )
            if risposta_connettore is not None:
                return risposta_connettore

    institutional_exhausted = not candidates and ente.access_mode in (
        AccessMode.M4_CONNETTORE,
        AccessMode.M5_NESSUNO,
    )
    letto_dal_vivo = False
    if institutional_exhausted:
        # D-58/D-60: un ente già censito sale la STESSA scala di uno fuori
        # copertura. Il bypass di prima — solo cache statica, mai sonda —
        # lasciava un orario cambiato ieri appeso al prossimo rigen (D-60);
        # ora il gradino 2 (la sonda sul portale) gira SEMPRE, anche qui.
        comune = comune_per_codice(ente.codice_istat)
        letto = None
        if comune is not None:
            try:
                letto = await asyncio.to_thread(leggi_orari_urp, comune)
            except Exception as exc:  # noqa: BLE001 — la rete che cade non è un 500
                logger.warning("sonda live fallita per %s: %s", ente.ente, exc)
                letto = None
        letto_dal_vivo = letto is not None and letto.ha_orari

        query = _websearch_query(topic=intent.topic, ente=ente)
        if query is not None:
            oggi = datetime.now(timezone.utc)
            entry = load_websearch(query)
            # D-60: la cache websearch è un HINT datato, non un sostituto
            # della ricerca. Entro TTL si mostra accanto al dato vivo col
            # proprio timbro; scaduta si ignora e si cerca di nuovo.
            if entry is not None and entry.results and entro_ttl(entry, oggi):
                web_results = [
                    WebResultAnswer(title=result.title, url=result.url)
                    for result in entry.results[:MAX_WEB_RESULTS_IN_REPLY]
                ]
                access_mode = AccessMode.M6_WEB_APERTO.value
                diagnosis = [
                    *diagnosis,
                    f"Ricerca web del {entry.fetched_at:%d/%m/%Y} (entro i "
                    "termini, non rifatta ora).",
                ]
            else:
                web_results, motivo_assenza = await _ricerca_a_gradini(
                    comune_sito=comune.sito if comune is not None else None,
                    query=query,
                )
                if web_results:
                    access_mode = AccessMode.M6_WEB_APERTO.value
                elif motivo_assenza:
                    diagnosis = [*diagnosis, motivo_assenza]

    coverage_count = len(candidates)
    reply = _compose_informazione_reply(
        ente_nome=ente.ente,
        document=document,
        web_results=web_results,
    )
    stato, prove = _prove_e_stato(
        document=document,
        office=office,
        web_results=web_results,
        letto_dal_vivo=letto_dal_vivo,
        ufficio_chiesto=_ufficio_chiesto(parole),
    )
    azioni = _azioni_possibili(document=document, office=office, web_results=web_results)

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
            letto_dal_vivo=letto_dal_vivo,
            stato=stato,
            prove=prove,
            azioni=azioni,
            ente_nome=ente.ente,
        ),
    )


#: Quanto si aspetta una ricerca web dentro una risposta. Corto come la sonda:
#: dall'altra parte c'è un cittadino, non un batch notturno.
TIMEOUT_RICERCA_LIVE = 6.0


def _query_ricerca_live(*, comune_nome: str, topic: Topic, ufficio: str | None) -> str:
    """La query, composta da campi e mai dal modello.

    L'ufficio che il cittadino ha nominato vale più del frammento generico del
    topic: chi chiede «i numeri dell'ufficio anagrafe» sta cercando quella
    pagina lì, non la sezione servizi del comune.
    """
    if ufficio:
        return f"ufficio {ufficio} comune di {comune_nome} contatti orari"
    frammento = WEBSEARCH_QUERY_FRAGMENTS.get(topic)
    if frammento:
        return f"{frammento} {comune_nome}"
    return f"URP ufficio relazioni con il pubblico comune di {comune_nome}"


def _cerca_sul_web(query: str) -> tuple[list[WebResultAnswer], str | None]:
    """Una ricerca web, ora, per un comune che non abbiamo censito.

    Il gradino 3 di D-32/D-58. I precedenti — lo snapshot curato e la lettura
    dal vivo del portale — restano davanti a questo e non vengono mai saltati:
    si arriva qui solo quando il portale ha risposto ma non espone i propri
    uffici in una forma leggibile da una macchina. Fino a ieri lì ci si
    fermava, e la chat diceva «cercalo a mano sul sito» per una pagina che un
    motore di ricerca trova al primo colpo.

    D-28 tiene la ricerca web fuori dall'ingestione, e resta fuori: quello che
    torna di qui non entra in nessuno snapshot, non diventa un record, non
    conta nella copertura. È un suggerimento a tempo, marcato `non_verificato`
    per costruzione (`WebResultAnswer`), da confermare con l'URP prima di
    fidarsene. Un dato di `enti.json` è stato letto, misurato e datato; questo
    è stato solo trovato, e la differenza deve restare visibile.

    Non solleva mai (D-59): un motore giù, lento, o senza chiave configurata
    è una risposta in meno, non una domanda fallita — mai un'eccezione al
    cittadino. Ritorna `(risultati, motivo_assenza)`: `motivo_assenza` è
    valorizzato solo quando la ricerca non è disponibile per costruzione
    (nessuna chiave Brave), cosicché il chiamante possa scriverlo in
    diagnosi invece di lasciarlo solo nei log. Una lista vuota senza motivo,
    però, non va mai presentata come «non esiste nulla» (R-15): significa
    solo che di qui non abbiamo visto niente.
    """
    try:
        risultati, _ = search_web(query, timeout=TIMEOUT_RICERCA_LIVE)
    except WebSearchNonConfigurato as exc:
        logger.info("ricerca web non disponibile per %r: %s", query, exc)
        return [], "La ricerca sul web non è disponibile in questo momento."
    except Exception:  # noqa: BLE001 — vedi docstring
        logger.warning("ricerca live fallita per %r", query, exc_info=True)
        return [], None
    return [
        WebResultAnswer(title=r.title, url=r.url)
        for r in risultati[:MAX_WEB_RESULTS_IN_REPLY]
    ], None


def _host_da_sito(sito: str) -> str | None:
    """Host nudo da un URL di sito comunale, per lo scoping `site:` (D-58)."""
    senza_schema = re.sub(r"^https?://", "", sito.strip(), flags=re.IGNORECASE)
    host = senza_schema.split("/", 1)[0].strip()
    return host or None


async def _ricerca_a_gradini(
    *, comune_sito: str | None, query: str
) -> tuple[list[WebResultAnswer], str | None]:
    """Gradino 3 in due passi (D-58): prima scoped al sito del comune, poi
    generico. L'ordine non si inverte mai: una pagina del comune stesso vale
    più di una qualunque pagina che lo nomina di sfuggita.

    Si ferma al primo passo che rende un motivo di assenza (es. Brave non
    configurato, D-59): il secondo tentativo fallirebbe per la stessa
    ragione, e riprovarlo sarebbe solo rumore.
    """
    if comune_sito:
        host = _host_da_sito(comune_sito)
        if host:
            risultati, motivo = await asyncio.to_thread(
                _cerca_sul_web, f"site:{host} {query}"
            )
            if risultati or motivo:
                return risultati, motivo
    return await asyncio.to_thread(_cerca_sul_web, query)


#: Sinonimi cittadino -> ufficio per il match sul connettore (B4). Il nome
#: dell'ufficio e' testo libero letto dal portale (Municipium oggi, altri
#: vendor domani): il match resta a sottostringa sul nome minuscolo, mai un
#: LLM (D-04) — se non ne torna esattamente uno, si elenca, non si indovina.
_SINONIMI_UFFICIO_CONNETTORE: dict[str, tuple[str, ...]] = {
    "anagrafe": ("anagrafe", "demografic", "stato civile"),
    "tributi": ("tribut", "imu", "tari"),
    "urbanistica": ("urbanistic", "edilizia"),
    "sociale": ("social",),
    "sociali": ("social",),
    # ciclo11 B5/A9: parola-chiave non derivata dal topic/testo nominato ma
    # dal filtro `disabilita`/`disabilita_nucleo` (riconosci_filtri) — vedi
    # `_ufficio_connettore_pertinente`.
    "disabilita": ("disabil", "social"),
    "scuola": ("scuola", "istruzion", "pubblica istruzione"),
    "commercio": ("commerci", "attivita produttive", "suap"),
    "polizia": ("polizia", "vigil"),
    "ambiente": ("ambiente", "ecologia"),
    "lavori": ("lavori pubblici", "manutenzion"),
    "protocollo": ("protocollo",),
    "cultura": ("cultura",),
    "sport": ("sport",),
}


def _ufficio_connettore_pertinente(
    uffici: list[UfficioConnettore],
    *,
    ufficio_chiesto: str | None,
    topic: Topic,
    disabilita_attiva: bool = False,
) -> tuple[UfficioConnettore | None, bool]:
    """L'ufficio del connettore che risponde alla domanda, se uno solo
    corrisponde. Prova prima la parola nominata dal cittadino
    (`_ufficio_chiesto`), poi — se il filtro disabilita/disabilita_nucleo e'
    acceso (ciclo11 B5/A9) — l'ufficio disabilita/servizi sociali, poi i
    pezzi del `topic` gia' riconosciuto — mai il testo libero del messaggio
    (D-24: solo campi tipizzati in ingresso al match).

    Il segnale del filtro RAFFINA quando puo', non forza (L-5): se nessun
    ufficio del connettore nomina disabilita/sociale, la ricerca prosegue
    esattamente come prima sui pezzi del topic — nessun ufficio inventato,
    nessun degrado silenzioso verso l'ufficio sbagliato.

    `(None, False)`: nessuna parola-chiave ha trovato un ufficio — il
    cittadino non ha nominato nulla di specifico, si elenca. `(None, True)`:
    piu' di un ufficio corrisponde alla stessa parola-chiave — ambiguo,
    stesso trattamento (elenco), mai un indovinello (D-04)."""
    candidati = []
    if ufficio_chiesto:
        candidati.append(ufficio_chiesto.lower())
    if disabilita_attiva:
        candidati.append("disabilita")
    candidati.extend(pezzo for pezzo in topic.value.split("_") if len(pezzo) > 3)

    for chiave in candidati:
        # La parola LETTERALE prima dei suoi sinonimi: se «anagrafe» compare in
        # un solo nome d'ufficio, è quello — anche quando i sinonimi
        # (demografic/stato civile) ne toccherebbero altri e renderebbero il
        # match «ambiguo». Un match letterale unico non è un indovinello
        # (D-04): un comune con più uffici demografici non deve ricadere
        # sull'URP per una parola che, presa alla lettera, è univoca.
        letterali = [u for u in uffici if chiave in u.nome.lower()]
        if len(letterali) == 1:
            return letterali[0], False

        sottostringhe = _SINONIMI_UFFICIO_CONNETTORE.get(chiave, (chiave,))
        trovati = [
            ufficio
            for ufficio in uffici
            if any(s in ufficio.nome.lower() for s in sottostringhe)
        ]
        if len(trovati) == 1:
            return trovati[0], False
        if len(trovati) > 1:
            return None, True
    return None, False


async def _office_da_ufficio_nominato(
    *,
    codice_istat: str,
    topic: Topic,
    ufficio_chiesto: str,
    disabilita_attiva: bool,
) -> OfficeAnswer | None:
    """L'ufficio NOMINATO dal cittadino, con il SUO orario letto adesso.

    Il rail informazione, di default, attacca l'URP di ripiego: chiesto
    «l'ufficio anagrafe», mostrava l'orario dell'URP. Il connettore conosce già
    la URL della pagina di quell'ufficio (catalogata dallo sweep): la si legge
    on-demand (`leggi_orari_ufficio`, cache-first + guardia SSRF) e se ne cita
    l'orario vero. Il match sull'ufficio riusa `_ufficio_connettore_pertinente`
    — stessa disciplina D-04 del ramo connettore, mai un ufficio indovinato.

    `None` (l'URP resta) quando il connettore non è leggibile, non espone
    uffici, o nessuno corrisponde in modo univoco alla parola nominata. Un
    orario non trovato NON è un `None`: si torna l'ufficio giusto con
    `orari=None`, così la scheda dice «non pubblicato per questo ufficio»
    invece di spacciare quello dell'URP (D-32).
    """
    esito = await asyncio.to_thread(connettore.leggi_connettore, codice_istat)
    if esito is None or not esito.uffici:
        return None
    # Stessa disciplina di match del ramo connettore (`_risposta_da_connettore`):
    # unica definizione di «quale ufficio intendeva», letterale-prima-dei-sinonimi
    # inclusa. Nessuna logica di match duplicata qui.
    ufficio, _ambiguo = _ufficio_connettore_pertinente(
        esito.uffici,
        ufficio_chiesto=ufficio_chiesto,
        topic=topic,
        disabilita_attiva=disabilita_attiva,
    )
    if ufficio is None or not ufficio.url:
        return None

    orari = await _orari_ufficio_live(codice_istat=codice_istat, ufficio=ufficio)
    return OfficeAnswer(
        nome=ufficio.nome,
        telefono=", ".join(ufficio.telefoni) or None,
        email=", ".join(ufficio.email) or None,
        orari=orari,
    )


async def _orari_ufficio_live(
    *, codice_istat: str, ufficio: UfficioConnettore
) -> str | None:
    """L'orario di QUESTO ufficio letto adesso dalla sua pagina, con ripiego
    onesto sul catalogo.

    Punto unico di lettura orari-per-ufficio, condiviso dai due percorsi
    INFORMAZIONE (rail URP/ingerito e ramo connettore): entrambi i comuni —
    dentro o fuori `enti.json` — leggono l'orario nello stesso modo, così
    nessuna famiglia di piattaforma ricade nel vecchio comportamento (orario
    sempre `None` perché lo sweep non lo cattura per-ufficio).

    Priorità all'orario letto ora da quella pagina (`leggi_orari_ufficio`,
    cache-first + guardia SSRF); poi quello eventuale già in catalogo; `None`
    onesto se nessuno dei due c'è. Mai solleva.
    """
    if not ufficio.url:
        return ufficio.orari
    letto = await asyncio.to_thread(
        leggi_orari_ufficio, codice_istat=codice_istat, url=ufficio.url
    )
    return (letto.orari if letto is not None else None) or ufficio.orari


def _testo_ufficio_connettore(*, comune_nome: str, ufficio: UfficioConnettore) -> str:
    """Frase-cornice fissa; tel/email/pec/orari sono interpolati VERBATIM
    dall'`UfficioConnettore` — mai passati da un LLM/verbalizzatore (D-07:
    il verbalizzatore corrompe le cifre, qui le cifre non lo incontrano
    nemmeno). Onesto campo per campo (D-05): un recapito compare solo se il
    comune lo ha pubblicato per questo ufficio, mai un centralino ente
    spacciato per diretto."""
    righe = [f"{comune_nome} pubblica sul proprio portale i recapiti di «{ufficio.nome}»."]
    if ufficio.telefoni:
        righe.append("Telefono: " + ", ".join(ufficio.telefoni) + ".")
    else:
        righe.append(f"Il comune non ha pubblicato un telefono diretto per {ufficio.nome}.")
    if ufficio.email:
        righe.append("Email: " + ", ".join(ufficio.email) + ".")
    if ufficio.pec:
        righe.append("PEC: " + ", ".join(ufficio.pec) + ".")
    if ufficio.orari:
        righe.append("Orari: " + ufficio.orari + ".")
    return " ".join(righe)


def _testo_elenco_uffici_connettore(*, comune_nome: str, uffici: list[UfficioConnettore]) -> str:
    """Elenco onesto quando il cittadino non ha nominato un ufficio preciso
    o ne ha nominato uno ambiguo (D-04): mai indovinare quale intendeva."""
    nomi = "; ".join(ufficio.nome for ufficio in uffici)
    return (
        f"{comune_nome} pubblica sul proprio portale questi uffici: {nomi}. "
        "Quale ti interessa?"
    )


async def _risposta_da_connettore(
    *,
    comune_nome: str,
    topic: Topic,
    diagnosi: list[str],
    esito: "connettore.EsitoConnettore",
    ufficio_chiesto: str | None,
    disabilita_attiva: bool = False,
) -> ChatAnswer | None:
    """Risposta INFORMAZIONE costruita dal connettore (B4, D-09/D-11): stesso
    schema di `_chat_live`, ma con recapiti VERBATIM e onestà campo-per-campo
    (D-05/D-07) invece del solo blocco `orari` che il resto del gradino 2
    conosce. `None` se il connettore non ha uffici da offrire su questo
    ramo — il chiamante ripiega sul gradino web (A7, invariato).

    `disabilita_attiva` (ciclo11 B5/A9): il filtro disabilita/disabilita_nucleo
    e' acceso per questo cittadino — raffina la selezione dell'ufficio verso
    disabilita/servizi sociali, vedi `_ufficio_connettore_pertinente`."""
    if not esito.uffici:
        return None

    ufficio, ambiguo = _ufficio_connettore_pertinente(
        esito.uffici,
        ufficio_chiesto=ufficio_chiesto,
        topic=topic,
        disabilita_attiva=disabilita_attiva,
    )
    diagnosi_connettore = [
        *diagnosi,
        f"Letto dal connettore ({esito.piattaforma}) il {esito.letto_il}.",
    ]

    if ufficio is None:
        reply = _testo_elenco_uffici_connettore(comune_nome=comune_nome, uffici=esito.uffici)
        documento = None
        ufficio_risposta = None
        citizen_effort = 2
    else:
        # Orario di QUESTO ufficio letto ora dalla sua pagina (stesso punto
        # unico del rail URP): lo sweep non cattura gli orari per-ufficio, così
        # lo store li ha `None` e senza questa lettura la scheda direbbe «non
        # pubblicato» anche dove la pagina li espone. Il valore migliore va
        # sostituito nell'ufficio così che ANCHE il testo (`_testo_ufficio_
        # connettore`) lo citi, non solo l'`OfficeAnswer`.
        migliore = await _orari_ufficio_live(codice_istat=esito.codice_istat, ufficio=ufficio)
        if migliore != ufficio.orari:
            ufficio = ufficio.model_copy(update={"orari": migliore})
        reply = _testo_ufficio_connettore(comune_nome=comune_nome, ufficio=ufficio)
        documento = DocumentAnswer(title=f"{ufficio.nome} — pagina del comune", url=ufficio.url)
        ufficio_risposta = OfficeAnswer(
            nome=ufficio.nome,
            telefono=", ".join(ufficio.telefoni) or None,
            email=", ".join(ufficio.email) or None,
            orari=ufficio.orari,
        )
        citizen_effort = 1

    stato, prove = _prove_e_stato(
        document=documento,
        office=ufficio_risposta,
        web_results=[],
        letto_dal_vivo=True,
    )
    azioni = _azioni_possibili(document=documento, office=ufficio_risposta, web_results=[])
    return ChatAnswer(
        reply=reply,
        topic=topic,
        kind=QuestionKind.INFORMAZIONE,
        data_gap=None,
        needs_clarification=ambiguo,
        matches=[],
        spid_required=False,
        spid_reason=None,
        access_mode=AccessMode.M4_CONNETTORE.value,
        citizen_effort=citizen_effort,
        info=InfoAnswer(
            document=documento,
            office=ufficio_risposta,
            stato=stato,
            prove=prove,
            azioni=azioni,
            coverage_count=0,
            diagnosis=diagnosi_connettore,
            letto_dal_vivo=True,
            integration_cost=[],
            web_results=[],
        ),
        esito_connettore=esito,
    )


async def _risposta_live(
    *,
    hint: str | None,
    topic: Topic,
    comune_istat: str | None = None,
    parole: str = "",
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
            # La citazione non sta più qui dentro. Ripetuta nella prosa e poi
            # resa nel blocco orari, la stessa riga compariva due volte: la
            # prima come muro di testo con dentro «Lunedì 09:00 - 12:30 |
            # Martedì…», la seconda leggibile. La prosa dice da dove viene il
            # dato, la scheda lo mostra — ognuno il proprio mestiere (D-24).
            reply=(
                f"{comune.nome} non è fra i comuni di cui abbiamo i dati: sono andato "
                "a leggere il suo portale adesso. Gli orari qui sotto sono quelli "
                "scritti sulla pagina del comune, riportati alla lettera."
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
        # Ciclo 15: una frase sola. Il «l'ho letto adesso» lo dice gia' il bollo
        # LETTO ORA, l'ufficio e il link stanno gia' nella card sotto.
        # R2: NON «non pubblica l'orario» — falso. L'orario spesso e' nella
        # pagina del comune; il connettore legge solo i dati in formato aperto,
        # quindi non lo prende in automatico. Rimando il cittadino alla pagina.
        reply = (
            f"L'ufficio «{letto.ufficio}» c'è. L'orario però non è tra i dati "
            "aperti che il connettore legge: aprilo dalla pagina qui sotto, "
            "oppure chiama il comune."
            if letto.ufficio
            else "Fra gli uffici pubblicati non ne trovo uno riconoscibile come "
            "anagrafe o URP: per l'orario apri la pagina del comune o chiama."
        )
        return _chat_live(
            reply=reply,
            topic=topic,
            diagnosi=diagnosi,
            comune_sito=comune.sito,
            ufficio=letto.ufficio,
            ufficio_url=letto.ufficio_url,
            access_mode=AccessMode.M2_PROSA_API.value,
            data_gap="not_published",
            citizen_effort=2,
        )

    # Innesto pre-web (B4, D-09/D-11): se il comune ha un connettore che sa
    # leggerlo (oggi Municipium), lo proviamo PRIMA della ricerca web aperta —
    # è dato letto dal portale stesso, non un risultato di un motore terzo
    # senza provenienza (A7: se non c'è connettore, si prosegue esattamente
    # come oggi, invariato).
    esito_connettore = await asyncio.to_thread(connettore.leggi_connettore, comune.codice_istat)
    if esito_connettore is not None and (
        esito_connettore.uffici or esito_connettore.amministrazione_trasparente is not None
    ):
        risposta_connettore = await _risposta_da_connettore(
            comune_nome=comune.nome,
            topic=topic,
            diagnosi=diagnosi,
            esito=esito_connettore,
            ufficio_chiesto=_ufficio_chiesto(parole),
            disabilita_attiva=_disabilita_attiva_nel_testo(parole),
        )
        if risposta_connettore is not None:
            return risposta_connettore

    # Gradino 3 (D-32). Il portale ha risposto e non espone i propri uffici in
    # una forma leggibile: fermarsi qui significava dire «cercalo a mano sul
    # sito» per una pagina che un motore di ricerca trova al primo colpo.
    # Cerchiamo noi, e diciamo con chiarezza che quello che torna non è un
    # nostro dato.
    ufficio_chiesto = _ufficio_chiesto(parole)
    web, motivo_assenza = await _ricerca_a_gradini(
        comune_sito=comune.sito,
        query=_query_ricerca_live(comune_nome=comune.nome, topic=topic, ufficio=ufficio_chiesto),
    )
    if web:
        return _chat_live(
            reply=(
                f"{comune.nome} ha un portale, ma non espone i propri uffici in una "
                "forma che si possa leggere da qui, quindi non è fra i comuni che "
                "copriamo. Ho cercato sul web mentre aspettavi: queste pagine sembrano "
                "quelle giuste, ma non le ho verificate."
            ),
            topic=topic,
            diagnosi=diagnosi,
            comune_sito=comune.sito,
            web_results=web,
            access_mode=AccessMode.M6_WEB_APERTO.value,
            data_gap="not_published",
            citizen_effort=len(web) + 1,
        )

    # D-59: se il motore non è disponibile per costruzione (niente chiave
    # Brave), lo si dice — non è la stessa cosa di "cercato e trovato niente"
    # (R-15), e il cittadino deve poterlo leggere, non solo trovarlo in log.
    diagnosi_finale = diagnosi if motivo_assenza is None else [*diagnosi, motivo_assenza]
    return _chat_live(
        reply=(
            f"{comune.nome} ha un portale, ma non espone i propri uffici in una forma "
            "che si possa leggere da qui: per sapere l'orario bisogna aprire il sito e "
            "cercarlo a mano. È il motivo per cui questo comune non è ancora fra quelli "
            "che copriamo."
        ),
        topic=topic,
        diagnosi=diagnosi_finale,
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
    web_results: list[WebResultAnswer] | None = None,
) -> ChatAnswer:
    """Confeziona una risposta live come INFORMAZIONE, mai come verdetto.

    `matches` resta vuoto e `spid_required` falso per costruzione: niente di
    letto dal vivo può diventare un giudizio di eleggibilità (D-01/D-32).

    `web_results` arriva solo dal gradino 3 (`_cerca_sul_web`) e resta una
    cosa diversa da tutto il resto: pagine trovate, non lette da noi. La
    scheda le mostra sotto la loro etichetta e `letto_dal_vivo` non le
    riguarda — quel bollo dice «letto dal portale del comune», che qui non è
    successo.
    """
    web = web_results or []
    documento = (
        DocumentAnswer(title=f"{ufficio} — pagina del comune", url=ufficio_url)
        if ufficio and ufficio_url
        else None
    )
    ufficio_risposta = (
        OfficeAnswer(nome=ufficio, telefono=None, email=None, orari=orari) if ufficio else None
    )
    stato, prove = _prove_e_stato(
        document=documento,
        office=ufficio_risposta,
        web_results=web,
        letto_dal_vivo=documento is not None or ufficio_risposta is not None,
    )
    if web:
        # «Il comune non pubblica un ufficio di riferimento» qui sarebbe falso:
        # Ciampino lo pubblica, siamo noi che non riusciamo a leggerlo. La riga
        # che segue dice la cosa vera al posto suo.
        prove = [p for p in prove if "non pubblica un ufficio" not in p.testo]
        prove.append(
            Prova(
                StatoProva.MANCANTE,
                "Di questo comune non abbiamo una fonte censita: queste pagine "
                "vanno confermate con l'URP prima di fidarsene",
            )
        )
    azioni = _azioni_possibili(document=documento, office=ufficio_risposta, web_results=web)
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
            office=ufficio_risposta,
            stato=stato,
            prove=prove,
            azioni=azioni,
            coverage_count=0,
            diagnosis=diagnosi,
            letto_dal_vivo=documento is not None or ufficio_risposta is not None,
            integration_cost=[
                "Lettura dal vivo, non un dato ingerito: nessuno snapshot di questo "
                "comune è stato salvato e nulla di quanto sopra entra nei dati del "
                "progetto finché non viene verificato."
            ],
            web_results=web,
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



#: Sotto questa lunghezza un token non e' un toponimo: e' una preposizione o
#: un articolo, e cercarlo fra i nomi dei comuni produce solo omonimie.
_MINIMO_TOPONIMO = 5

#: Connettivi lunghi >=5 che compaiono DENTRO i nomi ("Val DELLA Torre") ma non
#: distinguono nulla. Il filtro di lunghezza non li ferma: "della" ha 5 lettere.
#: Senza questo, una domanda come "bolletta DELLA luce" — che non nomina nessun
#: comune — agganciava le decine di "X della Y" e faceva partire una
#: disambiguazione su comuni mai nominati, scartando il comune di profilo.
#: Un nome reale che li contiene ("San Fermo della Battaglia") risolve comunque
#: attraverso le sue parole distintive (fermo, battaglia), quindi escluderli e'
#: sicuro. Non includere "santa"/"santo"/"monte"/"villa": quelli distinguono.
_CONNETTIVI_NOME = frozenset(
    {"della", "delle", "dello", "degli", "sulla", "sullo", "sugli", "sopra", "sotto"}
)

#: Parole italiane comunissime che sono ANCHE nomi (o parole di nomi) di comuni.
#: Diverse dai connettivi: quelle non distinguono, queste sono sostantivi pieni
#: che un cittadino scrive con il loro senso comune, non come toponimo. «minori»
#: e' Minori (SA) — comune singolo, quindi candidato unico che scavalcava in
#: silenzio: chi scriveva «contributi per i miei nipotini minori» finiva a
#: leggere il sito di Minori invece del proprio comune. «minore» e' la parola di
#: «Gorla Minore», ma «gorla» (5 lettere, distintiva) resta e risolve comunque
#: il nome intero — escludere la parola comune non toglie il comune vero. I
#: comuni cosi' nominati restano raggiungibili dal selettore, che usa l'ISTAT e
#: non passa da qui.
#:
#: «ora» e' il caso peggiore: comune di Ora (BZ), 3 lettere, chiave esatta
#: dell'indice. Sotto il minimo di 5 lettere il confronto per parola-nel-nome
#: non la vedrebbe mai, ma il match ESATTO in `_comuni_candidati` scavalca il
#: minimo — cosi' «a che ora apre l'ufficio?» finiva a leggere il sito di Ora
#: invece del comune del cittadino. E' un avverbio di tempo prima che un
#: toponimo: un cittadino di Ora (~3.600 ab.) resta comunque raggiungibile dal
#: selettore per ISTAT, che non passa di qui.
_PAROLE_NON_TOPONIMI = frozenset({"minori", "minore", "ora"})


@lru_cache(maxsize=1)
def _tutti_comuni() -> tuple:
    """Universo comuni, letto una volta e tenuto in cache (7896 righe)."""
    from treasureiq.sonda_live import _tutti as comuni_noti

    return tuple(comuni_noti())


@lru_cache(maxsize=1)
def _frequenza_parole_nome() -> dict:
    """Quante volte ogni parola compare nei nomi dei comuni.

    Serve a pesare i toponimi: «delle» sta in decine di nomi (connettivo, non
    distingue), «figline» in due (toponimo forte). Calcolata una volta sola.
    """
    freq: dict[str, int] = {}
    for comune in _tutti_comuni():
        for parola in set(comune.nome.lower().split()):
            freq[parola] = freq.get(parola, 0) + 1
    return freq


def _comuni_che_iniziano_per(message: str) -> list:
    """I comuni una cui parola del nome compare nel messaggio.

    Serve al caso che ha prodotto questo codice: «sono di pergine» non
    risolveva, perche' il risolutore esatto vuole il nome intero e di Pergine
    ce ne sono due — Valsugana in Trentino e Laterina Pergine Valdarno in
    Toscana.

    Senza questo, il messaggio non produceva nessun comune e la risposta
    ricadeva sul comune del profilo: i voucher di Albano Laziale a una persona
    che aveva scritto Pergine.

    Guardava solo la PRIMA parola del nome: «pergine» risultava sempre e solo
    Pergine Valsugana (mai ambiguo, sbagliato meta' delle volte) e «pergine
    valdarno» risolveva ANCORA a Pergine Valsugana, perche' "valdarno" non e'
    la prima parola di "Laterina Pergine Valdarno" e quindi non contava mai a
    favore del comune giusto. Ora si confronta ogni parola del nome: se le
    parole del messaggio coprono piu' parole di un solo candidato, quello
    vince da solo (e' un match piu' preciso, non una scelta a caso).

    Torna la lista, non una scelta: con due candidati pari la cosa giusta e'
    chiedere quale, non tirare a indovinare.
    """
    parole = {
        p.strip(".,;:!?'\"")
        for p in (message or "").lower().split()
        if len(p.strip(".,;:!?'\"")) >= _MINIMO_TOPONIMO
    }
    parole -= _CONNETTIVI_NOME
    parole -= _PAROLE_NON_TOPONIMI
    if not parole:
        return []
    freq = _frequenza_parole_nome()
    trovati = []
    for comune in _tutti_comuni():
        parole_nome = set(comune.nome.lower().split())
        corrispondenze = parole & parole_nome
        if not corrispondenze:
            continue
        # Peso IDF: una parola rara nei nomi («figline», in 2 comuni) e' un
        # toponimo forte; una comune («delle», in decine) e' un connettivo che
        # non distingue nulla. Contarle uguali faceva vincere il rumore: chi
        # scriveva «figline» riceveva i comuni con «delle», perche' erano molti
        # di piu' a pari conteggio. Col peso 1/freq il toponimo distintivo domina.
        punteggio = sum(1.0 / freq.get(p, 1) for p in corrispondenze)
        trovati.append((comune, punteggio))
    if not trovati:
        return []
    massimo = max(p for _, p in trovati)
    # Confronto float con tolleranza: due comuni che matchano la stessa parola
    # («figline») hanno lo stesso peso e vanno entrambi in disambiguazione.
    return [comune for comune, p in trovati if abs(p - massimo) < 1e-9]


def _quale_comune(candidati, intent) -> ChatAnswer:
    """Piu' comuni possibili: si chiede, non si sceglie.

    Scegliere il primo in ordine alfabetico sarebbe un sorteggio travestito da
    risposta, e chi legge non avrebbe modo di sapere che c'e' stato.
    """
    mostrati = candidati[:6]
    elenco = ", ".join(f"{c.nome} ({c.provincia})" for c in mostrati)
    return ChatAnswer(
        reply=(
            f"Fammi capire, di quale parliamo? In Italia ci sono piu' comuni "
            f"con questo nome: {elenco}. Tocca quello giusto qui sotto — "
            "preferisco chiedertelo piuttosto che sceglierne uno a caso e "
            "darti informazioni di un altro territorio."
        ),
        topic=intent.topic,
        kind=intent.kind,
        data_gap="comune_ambiguo",
        needs_clarification=True,
        matches=[],
        spid_required=False,
        spid_reason=None,
        # Le schede cliccabili: la UI le rende come chip, un tap sceglie e
        # rimanda la domanda con l'ISTAT. Niente da ridigitare.
        comuni_ambigui=[
            ComuneAmbiguo(nome=c.nome, provincia=c.provincia, codice_istat=c.codice_istat)
            for c in mostrati
        ],
    )


#: Quanti risultati live accompagnano una risposta su un comune non coperto.
#: Pochi di proposito: sono da verificare uno per uno, e una lista lunga di
#: cose da verificare non e' un servizio, e' un compito.
MASSIMO_LIVE = 3


def _prova_live(*, risposta: ChatAnswer, comune, message: str) -> ChatAnswer:
    """Cerca adesso sul sito del comune, quando non abbiamo dati suoi.

    Non produce un verdetto e non puo' produrlo: i risultati arrivano marcati
    `non_verificato`, senza criteri confrontati e senza «ti spetta». La regola
    che protegge il progetto resta intatta — un dato letto ora non decide una
    idoneita' — ma smette di impedire l'unica cosa utile che si puo' fare
    lo stesso: dire alla persona *dove guardare*.

    Non e' un ripiego elegante: e' un servizio peggiore di una risposta vera,
    ed e' meglio di un rifiuto.
    """
    if risposta.matches or risposta.info is not None:
        return risposta
    sito = (getattr(comune, "sito", None) or "").strip()
    if not sito:
        return risposta
    dominio = sito.replace("https://", "").replace("http://", "").strip("/")
    trovati, _motivo = _cerca_sul_web(f"site:{dominio} {message}")
    trovati = trovati[:MASSIMO_LIVE]
    if not trovati:
        return risposta
    return replace(
        risposta,
        info=InfoAnswer(
            document=None,
            office=None,
            coverage_count=0,
            diagnosis=[],
            integration_cost=[],
            web_results=trovati,
            letto_dal_vivo=True,
            stato=StatoFonte.NON_PUBBLICATO,
        ),
    )


def _indice_deterministico(chiave: str | None, modulo: int) -> int:
    """Indice stabile in [0, modulo) da una chiave testuale.

    Mai `hash()` nativo: e' randomizzato per processo (`PYTHONHASHSEED`), quindi
    la stessa chiave sceglierebbe una variante diversa ad ogni riavvio — e il
    video della demo deve restare riproducibile a ogni chiamata (KAPI 12, A2).
    """
    if not chiave:
        return 0
    return sum(ord(carattere) for carattere in chiave) % modulo


#: Varianti deterministiche della premessa fuori-copertura (KAPI 12, A2): stesso
#: contenuto onesto — ho controllato, il comune non e' ancora ingerito, non
#: posso essere certo — con parole diverse perche' non suoni da stampino.
#: Ciclo 15: una frase sola. La raggiungibilita' dal connettore la dice gia' il
#: BadgeConnettore (verde), i recapiti la card a sinistra: la prosa non li
#: ripete piu' (era il «pippone»). Il marker `[[Comune di ...]]` il frontend lo parsa.
_VARIANTI_PREMESSA_FUORI_COPERTURA = (
    "Controllato: il [[Comune di {luogo}]] non e' ancora tra quelli che "
    "leggiamo, quindi su cosa ti spetta non posso darti certezze.",
    "Il [[Comune di {luogo}]] non e' ancora tra quelli che leggiamo: su cosa "
    "ti spetta non posso essere certo.",
    "Sul [[Comune di {luogo}]] ho controllato, ma non e' ancora tra quelli che "
    "leggiamo — cosa ti spetta resta da confermare.",
)


def _premessa_fuori_copertura(
    nominato,
    risposta: ChatAnswer | None = None,
    connettore: "Connettore | None" = None,
    *,
    ha_scheda_laterale: bool = False,
) -> str:
    """La frase che apre una risposta su un comune che non leggiamo.

    Sta davanti al resto, non al posto del resto: quello che segue vale
    comunque, perche' le agevolazioni nazionali e regionali non dipendono da
    quale comune sappiamo leggere.

    Ciclo 15: la prosa non ripete piu' la raggiungibilita' dal Modello AgID ne'
    i recapiti «letti ora» — li dicono gia' il BadgeConnettore (verde) e la card
    a lato. La premessa resta una frase sola: ha controllato, non e' certo. Solo
    il ramo vicolo_cieco rimanda ancora alla scheda/mappa laterale se esistono.

    Il testo di apertura varia in 3 modi deterministici (indice dal codice
    ISTAT) — stesso contenuto onesto, meno stampino: dice sempre che ha
    controllato, ammette di non poter essere certo per QUESTO comune, e non
    inventa mai una copertura che non c'e' (D-05).
    """
    provincia = f" ({nominato.provincia})" if getattr(nominato, "provincia", None) else ""
    luogo = f"{nominato.nome}{provincia}"
    indice = _indice_deterministico(
        getattr(nominato, "codice_istat", None) or nominato.nome,
        len(_VARIANTI_PREMESSA_FUORI_COPERTURA),
    )
    base = _VARIANTI_PREMESSA_FUORI_COPERTURA[indice].format(luogo=luogo)
    # Ciclo 15: la raggiungibilita' dal Modello AgID e i recapiti «letti ora» non
    # si ripetono piu' in prosa — li dicono il BadgeConnettore (verde) e la card
    # a sinistra. La `connettore.indirizzabile` resta nella firma perche' serve
    # al ramo vicolo_cieco sotto (rimando alla mappa servizi di lato).
    # La frase si dice solo se sotto c'e' davvero qualcosa. Prometterla a
    # vuoto e' peggio di non prometterla: chi legge cerca risultati che non
    # esistono e conclude che l'interfaccia sia rotta, invece che la ricerca
    # non abbia trovato niente.
    trovati = (
        risposta is not None
        and risposta.info is not None
        and risposta.info.letto_dal_vivo
        and bool(risposta.info.web_results)
    )
    if trovati:
        return base + " Qui sotto la scansione live del loro sito: **da verificare tu**."
    # Vicolo cieco: la ricerca non ha collegato la domanda a nessun servizio.
    # Una frase sola, non tre «non ho trovato niente» impilati. Rimanda a cio'
    # che c'e' davvero attorno — la scheda di contatto a lato, la mappa dei
    # servizi sotto — nominando ciascuna via solo se esiste sul serio. Il nome
    # del comune diventa un tag colorato (`[[...]]`), «Attenzione» un grassetto
    # vero (`__...__`), non il chip giallo del «da verificare».
    vicolo_cieco = risposta is not None and getattr(risposta, "data_gap", None) == "none_found"
    if vicolo_cieco:
        frase = (
            f"__Attenzione__: la ricerca sulla domanda fatta per il "
            f"[[Comune di {nominato.nome}{provincia}]] non ha avuto un risultato chiaro"
        )
        indirizzabile = connettore is not None and connettore.indirizzabile
        if ha_scheda_laterale and indirizzabile:
            frase += (
                ". Trovi di lato la scheda del comune per contattarli direttamente, "
                "oppure la mappa dei loro servizi, sempre di lato, per cercare il "
                "settore giusto."
            )
        elif ha_scheda_laterale:
            frase += ". Trovi di lato la scheda del comune per contattarli direttamente."
        elif indirizzabile:
            frase += (
                ". Puoi navigare tra i loro servizi, di lato, e cercare il settore giusto."
            )
        else:
            frase += ". Prova a riformularla, oppure rivolgiti direttamente all'URP del comune."
        return frase
    # Ciclo 15: `base` e' gia' una frase onesta e completa. La bridge appesa
    # («quello che segue vale comunque...») era filler — via.
    return base


def _numeri_utili_al_volo(codice_istat: str | None) -> "NumeriUtili | None":
    """Legge i recapiti del comune ADESSO e li impacchetta per il pannello.

    Non e' una richiesta esplicita del cittadino: e' il biglietto da visita del
    comune fuori copertura, che mettiamo a sinistra insieme allo stato. Fonte
    sempre «scansione web» — l'API AgID espone la struttura uffici, non i
    recapiti, quindi la sorgente reale resta lo scrape della home. `letto_il` e'
    l'ora del recupero, che il pannello rende come «ultimo controllo». Muto: se
    lo scrape non trova nulla di utile, torna None e il pannello non compare.
    """
    contatti = recupera_contatti(codice_istat)
    if contatti is None:
        return None
    if not (contatti.telefoni or contatti.email or contatti.pec):
        return None
    return NumeriUtili(
        telefoni=list(contatti.telefoni),
        email=list(contatti.email),
        pec=list(contatti.pec),
        fonte=contatti.fonte,
        fonte_tipo="scansione web",
        letto_il=datetime.now(timezone.utc).isoformat(),
    )


def _numeri_utili_da_store(codice_istat: str | None) -> "NumeriUtili | None":
    """Il biglietto da visita di un comune COPERTO: recapiti già scansionati.

    Gemello di `_numeri_utili_al_volo`, ma NON sonda: legge lo store (D-S4),
    così l'happy-path della chat non paga uno scrape live a ogni risposta. La
    fonte resta la scansione, e `letto_il` è `scansionato_il` del record — non
    un `now()` al volo — perché quello è il momento in cui i recapiti sono
    stati davvero letti. Muto se non c'è record o non ci sono recapiti.
    """
    record = carica_scansione(codice_istat)
    contatti = getattr(record, "contatti", None) if record is not None else None
    if contatti is None:
        return None
    if not (contatti.telefoni or contatti.email or contatti.pec):
        return None
    return NumeriUtili(
        telefoni=list(contatti.telefoni),
        email=list(contatti.email),
        pec=list(contatti.pec),
        fonte=contatti.fonte,
        fonte_tipo="scansione web",
        letto_il=record.scansionato_il,
    )


def _fuori_copertura(nominato, intent) -> ChatAnswer:
    """Il cittadino ha nominato un comune che non leggiamo.

    Dirlo e' l'unica risposta onesta. L'alternativa — rispondere con i dati di
    un comune diverso — non e' una risposta imprecisa: e' la risposta di un
    altro territorio, e chi legge non ha modo di accorgersene.

    Il nome del comune compare per esteso proprio per questo: se sbagliamo a
    riconoscerlo, la persona lo vede subito e puo' correggerci.
    """
    return ChatAnswer(
        reply=(
            f"Non copro ancora il Comune di {nominato.nome}"
            f"{f' ({nominato.provincia})' if getattr(nominato, 'provincia', None) else ''}. "
            "Preferisco dirtelo piuttosto che risponderti con i dati di un altro "
            "comune: sarebbero informazioni sbagliate per te, e non avresti modo "
            "di accorgertene. Se ti interessa un comune che leggo, scrivimene il "
            "nome."
        ),
        topic=intent.topic,
        kind=intent.kind,
        data_gap="comune_non_coperto",
        needs_clarification=True,
        matches=[],
        spid_required=False,
        spid_reason=None,
    )


_CAMBIO_PERSONA_RE = re.compile(
    r"\bmia\s+madre\b|\bmio\s+padre\b|\bmia\s+figlia\b|\bmio\s+figlio\b"
    r"|\bper\s+lei\b|\bper\s+lui\b",
    re.IGNORECASE,
)

# KAPI 11 (gap-closure): sinonimi civici di "agevolazione" nel messaggio.
# Insieme chiuso, deciso dal committente — «Aggiungi bandi», non un reroute
# di topic (D-01): accende SOLO una scansione bandi live additiva accanto
# alla risposta agevolazione, mai al suo posto. «aiuto/aiuti» ESCLUSO di
# proposito: troppo generico, produrrebbe falsi positivi su ogni domanda
# di supporto non civico.
_BANDI_SINONIMI_RE = re.compile(
    r"\b(?:agevolazion\w*|contribut\w*|sovvenzion\w*|sussid\w*|bonus|incentiv\w*)\b",
    re.IGNORECASE,
)

# Le stesse chiavi che `_profile_from_slots` legge dal turno corrente via
# `riconosci_filtri` (ciclo11): se almeno una e' dichiarata insieme al
# pattern sopra, il turno non sta aggiornando la persona in sessione — ne
# descrive un'altra (A3). Non c'e' una chiave FiltroChiave per il sesso (resta
# fuori dal catalogo, D-52): controllato a parte sotto.
_SLOT_ANAGRAFICI_FILTRO = (
    "eta",
    "isee",
    "nucleo_familiare",
    "disabilita_nucleo",
    "figli_minori",
    "disabilita",
    "employment_status",
)


def _e_cambio_persona(message: str) -> bool:
    """D-56/A3: euristica deterministica, niente LLM. Il pattern da solo non
    basta (si puo' nominare la madre senza chiedere nulla su di lei); serve
    anche almeno uno slot anagrafico dichiarato in QUESTO turno.

    Ciclo11: letto ora da `riconosci_filtri` (lazy import, stesso motivo di
    `_profile_from_slots`), non piu' da `intent.slots` — sempre vuoto dopo
    D-01, il modello non riempie piu' gli slot."""
    if not _CAMBIO_PERSONA_RE.search(message):
        return False
    from treasureiq.chat.filtri import riconosci_filtri

    chiavi = {f.chiave.value for f in riconosci_filtri(message)}
    if any(chiave in chiavi for chiave in _SLOT_ANAGRAFICI_FILTRO):
        return True
    return _sesso_dichiarato_nel_testo(message) is not None


def _affinita_bando(opp: Opportunity, profile: CitizenProfile) -> int:
    """Punteggio MORBIDO di aderenza profilo↔bando. Non è un verdotto: serve a
    ORDINARE, mai a escludere. I requisiti tipizzati pesano più delle parole
    nel titolo. Zero significa «nessun riscontro», non «non idoneo» — un bando
    a punteggio 0 resta in lista, solo più in basso.

    Deliberatamente prudente sui `None`: un requisito non dichiarato non è un
    match (schema `Requirements`: `None` ≠ «nessun vincolo»). Non tocca ISEE né
    scadenze — quelle restano dietro il quote-gate, mai dedotte qui."""
    req = opp.requirements
    testo = f"{opp.title} {opp.summary or ''}".lower()
    punti = 0

    # Figli minori: segnale strutturato forte, poi il richiamo nel titolo.
    if profile.figli_minori and profile.figli_minori > 0:
        if req.figli_minori_required is True:
            punti += 2
        if TargetGroup.MINORI in opp.targets or any(
            k in testo
            for k in (
                "minor",
                "figli",
                "bambin",
                "infanz",
                "scuola",
                "scolast",
                "asilo",
                "nido",
                "student",
                "mensa",
                "doposcuola",
            )
        ):
            punti += 1

    # Famiglia / nucleo.
    ha_famiglia = bool(profile.figli_minori) or bool(
        profile.nucleo_familiare and profile.nucleo_familiare > 1
    )
    if ha_famiglia and (TargetGroup.FAMIGLIE in opp.targets or "famigl" in testo):
        punti += 1
    if (
        req.nucleo_min is not None
        and profile.nucleo_familiare
        and profile.nucleo_familiare >= req.nucleo_min
    ):
        punti += 1

    # Età: dentro la forbice dichiarata, o la fascia anziani.
    if profile.eta is not None:
        if (
            req.eta_min is not None
            and req.eta_max is not None
            and req.eta_min <= profile.eta <= req.eta_max
        ):
            punti += 1
        if profile.eta >= 65 and (
            TargetGroup.ANZIANI in opp.targets or "anzian" in testo
        ):
            punti += 1

    # Disabilità: del cittadino e del nucleo, distinte (D-53).
    if profile.disabilita and req.disabilita_required is True:
        punti += 2
    if profile.disabilita_nucleo and req.disabilita_nucleo_required is True:
        punti += 2

    # Sesso (bandi riservati, es. contrassegno rosa) e stato occupazionale.
    if req.sesso is not None and profile.sesso is not None and req.sesso == profile.sesso:
        punti += 1
    if req.employment_status and profile.employment_status in req.employment_status:
        punti += 1

    return punti


def _ordina_bandi_per_profilo(
    bandi: list[BandoArricchito], profile: CitizenProfile | None
) -> tuple[list[BandoArricchito], bool]:
    """Ordina i bandi per aderenza morbida al profilo e marca i risuonanti.
    Ritorna `(lista, c_e_ranking)`. Ordinamento STABILE: a pari punteggio
    l'ordine del portale è preservato. NESSUNA esclusione — la lista resta
    intera. Senza profilo o senza alcun riscontro torna la lista intatta e
    `False`, così il testo non promette un filtro che non c'è stato."""
    if profile is None or not bandi:
        return bandi, False
    valutati = [
        (_affinita_bando(b.opportunity, profile), indice, b)
        for indice, b in enumerate(bandi)
    ]
    if not any(punti > 0 for punti, _, _ in valutati):
        return bandi, False
    valutati.sort(key=lambda t: (-t[0], t[1]))
    ordinati = [
        b.model_copy(update={"consigliato": punti > 0}) for punti, _, b in valutati
    ]
    return ordinati, True


#: Parole-funzione italiane che non portano alcun tema: articoli,
#: preposizioni, ausiliari e le forme più comuni in cui un cittadino
#: introduce una domanda sui bandi («ci sono bandi per...», «avete bandi
#: sulla...»). Tagliate qui, non nel keyword-hit: `_estrai_tema` deve
#: restare deterministico e non dipendere dal matching morbido del match
#: engine.
_STOPWORD_TEMA = frozenset(
    {
        "ci",
        "sono",
        "per",
        "di",
        "la",
        "lo",
        "il",
        "le",
        "gli",
        "un",
        "una",
        "uno",
        "che",
        "cosa",
        "quali",
        "quale",
        "qualche",
        "qualcuno",
        "avete",
        "esistono",
        "esiste",
        "trovo",
        "posso",
        "vorrei",
        "sapere",
        "se",
        "e",
        "ed",
        "o",
        "ma",
        "anche",
        "solo",
        "ancora",
        "gia",
        "già",
        "non",
        "mi",
        "ti",
        "si",
        "noi",
        "voi",
        "loro",
        "dei",
        "nel",
        "nello",
        "nella",
        "nei",
        "negli",
        "nelle",
        "al",
        "allo",
        "alla",
        "ai",
        "agli",
        "alle",
        "dal",
        "dallo",
        "dalla",
        "dai",
        "dagli",
        "dalle",
        "sul",
        "sui",
        "sulle",
        "con",
        "tra",
        "fra",
        "come",
        "dove",
        "quando",
        "perché",
        "perche",
        "cui",
        "questo",
        "questa",
        "questi",
        "queste",
        "suo",
        "sua",
        "suoi",
        "sue",
        "mio",
        "mia",
        "miei",
        "mie",
        "nostro",
        "nostra",
        # filler modali/verbi-domanda: compaiono nella coda dopo «bandi»
        # («bandi a cui posso accedere») senza essere un tema.
        "accedere",
        "richiedere",
        "ottenere",
        "avere",
        "fare",
        "usufruire",
        "partecipare",
        "aperti",
        "aperto",
        "attivi",
        "attivo",
        "disponibili",
        "disponibile",
        "adesso",
        "ora",
        # saluti/presentazione: di norma precedono «bandi» (già esclusi dal
        # taglio sulla coda), ma tenerli qui è una rete di sicurezza a costo zero.
        "ciao",
        "salve",
        "buongiorno",
        "buonasera",
        "grazie",
        "scusa",
        "scusi",
    }
)

#: Tetto alla lunghezza del tema estratto (D-06, red-team): il tema finisce
#: eco-iato verbatim dentro la reply, quindi un messaggio patologicamente
#: lungo non deve produrre una risposta patologicamente lunga. Non è HTML e
#: non gira in una shell — è solo interpolazione di stringa — ma un limite
#: onesto tiene la risposta leggibile.
_TEMA_MAX_CHARS = 60


def _estrai_tema(message: str) -> str | None:
    """Estrae dal messaggio del cittadino il tema di un filtro sui bandi
    («ci sono bandi per la mobilità?» → "mobilità"), deterministico (D-01):
    nessun modello, solo sottrazione di ciò che non è tema.

    Il tema è ciò che il cittadino aggiunge DOPO aver nominato i bandi:
    «bandi per la mobilità», «avviso pubblico sulla casa». Quindi si guarda
    solo la CODA che segue l'ultima keyword di `TOPIC_KEYWORDS[Topic.BANDI]`
    ("bando", "bandi", "avviso pubblico", "avvisi pubblici", "graduatoria").
    Saluti, nome e presentazione precedono sempre la keyword («ciao sono
    Andrea, vivo a Benevento, avete bandi?») e così non possono mai essere
    scambiati per un tema — la causa del falso-positivo emersa in review.
    Se nel messaggio non compare nessuna keyword bandi, non c'è un segnale
    esplicito di tema: `None`, e il ramo si comporta come prima (D-07).

    Sulla coda, ordine di sottrazione (ognuno riduce il residuo successivo):

    1. Le parole del nome del comune già riconosciuto da `_comune_nominato`
       (stessa funzione usata per il routing, R-9) — chi nomina il comune
       non sta nominando un tema.
    2. `_STOPWORD_TEMA`: parole-funzione, saluti, verbi-domanda («a cui posso
       accedere») comuni in una domanda.
    3. `_CONNETTIVI_NOME` e `_PAROLE_NON_TOPONIMI`: riusate qui non per il
       loro scopo originale (disambiguare comuni), ma perché sono comunque
       parole-funzione o non-contenuto già validate altrove.
    4. Token sotto le tre lettere — troppo corti per portare un tema.

    Quel che resta, nell'ordine in cui compare, è il tema — ma solo se sono
    1-3 parole (DISCRETION): residui più lunghi sono rumore di frase, non un
    filtro. Unito con uno spazio e troncato a `_TEMA_MAX_CHARS` (D-06,
    red-team «tema enorme»). Se non resta nulla o restano troppe parole:
    `None` (D-07).

    Il tema è un'eco: mai tradotto, riformulato o passato a un modello
    (A5). Se sembra sbagliato al cittadino, resta comunque leggibile perché
    sono le sue stesse parole.
    """
    testo = message.lower()
    # Fine dell'ULTIMA keyword bandi nel messaggio: il tema vive nella coda.
    fine_keyword = -1
    for frase in TOPIC_KEYWORDS[Topic.BANDI]:
        inizio = 0
        while (pos := testo.find(frase, inizio)) >= 0:
            fine_keyword = max(fine_keyword, pos + len(frase))
            inizio = pos + len(frase)
    if fine_keyword < 0:
        return None
    coda = testo[fine_keyword:]
    comune = _comune_nominato(message)
    parole_comune = set(comune.nome.lower().split()) if comune is not None else set()
    parole = re.findall(r"[a-zà-ù']+", coda)
    residuo = [
        parola
        for parola in parole
        if len(parola) >= 3
        and parola not in _STOPWORD_TEMA
        and parola not in _CONNETTIVI_NOME
        and parola not in _PAROLE_NON_TOPONIMI
        and parola not in parole_comune
    ]
    if not residuo or len(residuo) > 3:
        return None
    tema = " ".join(residuo).strip()
    return tema[:_TEMA_MAX_CHARS] if tema else None


def _bando_tocca_il_tema(bando: BandoArricchito, tema: str) -> bool:
    """Se `tema` (estratto da `_estrai_tema`) trova riscontro nel bando:
    titolo e riassunto insieme, stesso haystack usato da `_pertinente` per lo
    stesso motivo — il titolo porta l'argomento, il riassunto lo completa
    quando il titolo da solo è troppo scarno. Riusa `_keyword_hit` (726):
    stessa logica di match già validata (parola intera + radici tronche),
    non una nuova euristica per lo stesso problema.

    Tema multi-parola: match ANY-token (default spec DISCRETION «almeno uno»),
    non frase-intera contigua — «servizi sociali» tocca un bando che nomina
    solo «sociali». Ogni token del tema è una keyword separata per
    `_keyword_hit`, che va già a OR sulle keyword.
    """
    haystack = f"{bando.opportunity.title} {bando.opportunity.summary or ''}".lower()
    return _keyword_hit(haystack=haystack, keywords=tuple(tema.split()))


async def _risposta_bandi(
    *, message: str, profile: CitizenProfile | None, comune_istat: str | None
) -> ChatAnswer:
    """Ramo Topic.BANDI (KAPI 7, bandi-live-agid): legge dal vivo la sezione
    Amministrazione Trasparente del comune, invece di cercare nello snapshot
    ingerito che alimenta `_search_opportunities` — un bando pubblicato oggi
    non e' nell'ultima fotografia dell'ingestione.

    Il comune segue la precedenza qui sotto: il PROFILO vince sempre (R-9,
    memoria «ricerca live cieca al comune di profilo») — un cittadino il cui
    profilo ha gia' un comune non deve vedersi scansionare un comune diverso
    solo perche' lo ha nominato di sfuggita — poi la scelta esplicita, e SOLO
    in assenza di entrambi il comune nominato nel testo (indispensabile al
    primo turno, quando profilo e scelta sono ancora vuoti), infine il default.

    Il testo di risposta e' FISSO, mai passato al verbalizzatore (D-07,
    memoria «il verbalizzatore corrompe le cifre»): requisiti, importi e
    scadenze di ogni bando viaggiano solo in `ChatAnswer.bandi_live`, il
    `BandiLiveEsito` cosi' come l'ha prodotto `bandi_live.bandi_arricchiti`.

    I bandi coperti vengono ORDINATI per aderenza morbida al profilo
    (`_ordina_bandi_per_profilo`) — indicazione, non verdetto: nessuno viene
    escluso, e il testo lo dice esplicitamente.

    Degradazione onesta se la scansione solleva (portale irraggiungibile,
    timeout, risposta non valida): mai un'eccezione al cittadino.
    """
    # Precedenza del comune per la scansione bandi:
    #  1. il comune del PROFILO (sessione/SPID) vince sempre: un cittadino con un
    #     comune gia' stabilito non deve vedersi scansionare un comune diverso
    #     solo perche' l'ha nominato di sfuggita (memoria «ricerca live cieca al
    #     comune di profilo», R-9).
    #  2. l'istat di una scelta scheda esplicita.
    #  3. SOLO se non c'e' ne' profilo ne' scelta: il comune NOMINATO in QUESTO
    #     messaggio («vivo a Benevento, ci sono bandi?»). Sul primo turno il
    #     profilo client non e' ancora popolato e non arriva `comune_istat`:
    #     senza questo si cadeva sul default Albano leggendo il comune sbagliato.
    #     `_comune_nominato` usa `_comuni_candidati` (stoplist
    #     «bolletta»/«minori»/connettivi), niente falsi toponimi.
    #  4. default demo, solo come ultima risorsa.
    nominato = _comune_nominato(message)
    target_istat = (
        (profile.comune_istat if profile is not None else None)
        or comune_istat
        or (nominato.codice_istat if nominato is not None else None)
        or DEFAULT_COMUNE_ISTAT
    )

    try:
        esito = await asyncio.to_thread(bandi_live.bandi_arricchiti, target_istat)
    except Exception:
        logger.warning("bandi_arricchiti fallita per %s", target_istat, exc_info=True)
        return ChatAnswer(
            reply=(
                "Non sono riuscito a leggere ora la sezione Amministrazione "
                "Trasparente del comune. Riprova tra qualche minuto, oppure "
                "rivolgiti direttamente all'URP."
            ),
            topic=Topic.BANDI,
            kind=QuestionKind.INFORMAZIONE,
            data_gap="not_verified",
            needs_clarification=False,
            matches=[],
            spid_required=False,
            spid_reason=None,
            access_mode=None,
            citizen_effort=1,
            info=None,
            bandi_live=None,
        )

    if esito.esito == "comune_ignoto":
        reply = (
            "Non riconosco questo comune per la ricerca dei bandi. Verifica "
            "il comune scelto e riprova."
        )
        data_gap = "comune_sconosciuto"
    elif esito.esito == "non_coperto":
        # Testo advocacy: il frontend lo aggancia a `ChiediApertura`, non e'
        # un rifiuto ma un invito a chiedere l'apertura dei dati al comune.
        reply = (
            f"Il portale di {esito.comune_nome} non pubblica ancora i bandi in "
            "un formato che riesco a leggere in automatico. Non e' un dato "
            "negato, e' un'apertura che manca: puoi chiedere al comune di "
            "pubblicarli in un formato leggibile."
        )
        data_gap = "comune_non_indirizzabile"
    elif esito.esito == "coperto_senza_bandi":
        reply = (
            f"Ho letto ora la sezione Amministrazione Trasparente di "
            f"{esito.comune_nome}. Verificato il {esito.verificato_il}. "
            "Nessun bando pubblicato al momento."
        )
        data_gap = "none_found"
    else:  # coperto_con_bandi
        # Filtro conversazionale (KAPI 9, ciclo bandi-conversazionale): se il
        # cittadino ha nominato un tema («bandi per la mobilità?»), lo
        # eco-iamo nella risposta e marchiamo quali bandi lo riguardano — MAI
        # li togliamo dall'esito, solo li mettiamo in cima (D-07: nessun tema
        # ⇒ risposta identica a prima di questo ciclo, byte per byte).
        tema = _estrai_tema(message)
        if tema is None:
            reply = (
                f"Ho letto ora la sezione Amministrazione Trasparente di "
                f"{esito.comune_nome}. Verificato il {esito.verificato_il}."
            )
        else:
            bandi_con_match = [
                bando.model_copy(
                    update={"corrisponde": _bando_tocca_il_tema(bando, tema)}
                )
                for bando in esito.bandi
            ]
            matched = [b for b in bandi_con_match if b.corrisponde]
            non_matched = [b for b in bandi_con_match if not b.corrisponde]
            esito = esito.model_copy(
                update={"bandi": matched + non_matched, "tema": tema}
            )
            if matched:
                verbo = "corrisponde" if len(matched) == 1 else "corrispondono"
                reply = (
                    f"Ho cercato «{tema}» tra i bandi di {esito.comune_nome}: "
                    f"{len(matched)} {verbo}."
                )
            else:
                reply = (
                    f"Nessun bando corrisponde a «{tema}»; te li mostro "
                    f"tutti ({len(esito.bandi)})."
                )
        data_gap = None
        # Ordinamento morbido per aderenza al profilo. Non esclude nulla: se
        # qualche bando risuona coi segnali del cittadino, lo porta in cima e
        # aggiunge una riga onesta — è un'indicazione, non un verdetto, e i
        # requisiti restano da controllare (schema `Confidence`: un falso «ti
        # spetta» costa al cittadino una domanda persa e la fiducia).
        bandi_ordinati, c_e_ranking = _ordina_bandi_per_profilo(esito.bandi, profile)
        if c_e_ranking:
            esito = esito.model_copy(update={"bandi": bandi_ordinati})
            reply += (
                " Li ho messi in ordine di aderenza al tuo profilo: è "
                "un'indicazione, non un verdetto di idoneità — controlla i "
                "requisiti di ciascuno."
            )

    return ChatAnswer(
        reply=reply,
        topic=Topic.BANDI,
        kind=QuestionKind.INFORMAZIONE,
        data_gap=data_gap,
        needs_clarification=False,
        matches=[],
        spid_required=False,
        spid_reason=None,
        access_mode=None,
        citizen_effort=0,
        info=None,
        bandi_live=esito,
    )


#: Varianti deterministiche della domanda «tutte o una categoria?» (KAPI 12,
#: A2): nessuna informazione nuova, solo parole diverse cosi' non ripete la
#: frase identica ad ogni turno di chiarimento categoria.
_VARIANTI_RICHIESTA_CATEGORIA = (
    "Cerco tra tutte le agevolazioni del Comune, o preferisci restringere a "
    "una categoria — utenze, mezzi o assegni?",
    "Posso guardare tutte le agevolazioni del Comune, oppure restringo a una "
    "categoria — utenze, mezzi o assegni: tu che dici?",
)

#: Varianti deterministiche del vicolo cieco su topic non riconosciuto (KAPI
#: 12, A2): stesso contenuto (nessun servizio collegato, riformula o passa
#: dall'URP), parole diverse. `{comune}` e' il nome del comune di riferimento,
#: mai un dato inventato — resta "riferimento" quando non c'e' un comune scelto.
_VARIANTI_TOPIC_SCONOSCIUTO = (
    "Non sono riuscito a collegare la tua richiesta a un servizio del Comune "
    "di {comune}. Puoi provare a riformularla, oppure rivolgerti direttamente "
    "all'URP del Comune per essere indirizzato all'ufficio competente.",
    "Non sono riuscito a collegare questa richiesta a un servizio del Comune "
    "di {comune}. Ti conviene riformularla, oppure puoi rivolgerti "
    "direttamente all'URP del Comune: sapranno indirizzarti all'ufficio giusto.",
)


async def _componi_risposta(
    *,
    message: str,
    profile: CitizenProfile | None,
    records: list[Opportunity],
    storia: list[str] | None = None,
    comune_istat: str | None = None,
    comune_coperto: bool = True,
    today: date | None = None,
    filtri_esclusi: frozenset | None = None,
    comune_bandi_istat: str | None = None,
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
    intent = await extract_intent(message=message, provider=provider, storia=storia)

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

    # Le parole del cittadino devono poter contraddire il profilo.
    #
    # Prima non potevano: se il profilo aveva un comune — e per difetto ce
    # l'aveva, Albano Laziale — `risolvi_comune(message)` non veniva nemmeno
    # chiamata. Una persona che scriveva «sono di Pergine» riceveva i voucher
    # di Albano senza che da nessuna parte comparisse la parola Albano.
    #
    # Non e' una risposta imprecisa: e' la risposta di un altro comune, ed e'
    # il solo errore che questo progetto non puo' permettersi, perche' e'
    # indistinguibile da una risposta giusta per chi legge.
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

    # D-55: se questo turno stesso risponde alla domanda «tutte le categorie
    # o una in particolare?» — letto sul testo grezzo, mai sulla
    # classificazione del modello, per lo stesso motivo per cui `_quale_comune`
    # non si fida del modello per il comune: «tutte»/«utenze»/«mezzi»/«assegni»
    # non sono nel vocabolario di `Topic`, e un modello a cui viene chiesto di
    # classificarli tenderebbe a inventare un topic vicino piuttosto che
    # ammettere di non saperlo.
    richiesta_categoria = _categoria_richiesta(message)

    # R-8/D-19: `_backfill_ambiguous_topic` can restore a topic (VOLONTARIATO,
    # RIFIUTI) that `extract_intent` classified as SCONOSCIUTO and therefore
    # never saw the informational override for. Re-assert it here so an
    # informational-by-nature topic can never fall through to the engine and
    # produce a verdict, whatever `kind` the model emitted on the bare reply.
    if intent.topic in INFORMATIONAL_BY_NATURE_TOPICS:
        intent = intent.model_copy(update={"kind": QuestionKind.INFORMAZIONE})

    # KAPI 7 (bandi-live-agid): i bandi si leggono dal vivo, non dallo
    # snapshot ingerito che alimenta `_search_opportunities` — questo ramo
    # bypassa sia il rail INFORMAZIONE generico sia quello AGEVOLAZIONE, un
    # bando e' un elenco, non un verdetto di `match/engine.py`.
    # `_tema_sostenuto` e' lo stesso riscontro lessicale che gli altri topic
    # ottengono dalla ricerca per parole chiave: senza le parole del
    # cittadino a confermarlo, un BANDI del modello non ancorato non basta a
    # far partire una scansione di rete.
    if intent.topic is Topic.BANDI and _tema_sostenuto(topic=Topic.BANDI, testo=message):
        # Come gli altri rail (righe ~2660/2749): se non c'è un profilo di
        # sessione, si ricava dai segnali di QUESTO turno. Senza, il ramo bandi
        # scattava prima e restava cieco al «vedovo, 2 figli minori» appena
        # scritto — niente da cui ordinare i bandi per aderenza (bug Andrea #2).
        profilo_bandi = profile or _profile_from_slots(intent=intent, messaggio=message, filtri_esclusi=filtri_esclusi)
        # `comune_bandi_istat`: il comune per la SCANSIONE bandi, quando il ramo
        # fuori-copertura di `build_chat_answer` passa `comune_istat=None` (per
        # non contaminare records/naming agevolazione) ma conosce comunque il
        # comune del cittadino via `nominato`. Senza, la scansione ripiegava sul
        # DEFAULT Albano — un residente a Bisceglie chiedeva i bandi e vedeva
        # quelli di Albano. Vale solo per i bandi: agevolazione/info restano su
        # `comune_istat` come prima. Fallback a `comune_istat` sul ramo coperto.
        return await _risposta_bandi(
            message=message,
            profile=profilo_bandi,
            comune_istat=comune_bandi_istat or comune_istat,
        )

    if intent.topic is Topic.SCONOSCIUTO and richiesta_categoria is None:
        # D-55: un topic sconosciuto/generico ("che bonus posso avere?") con
        # un profilo già ricco non merita lo stesso "non ho capito" di una
        # domanda davvero fuori catalogo — il cittadino ha già dato abbastanza
        # di sé perché valga la pena chiedere SOLO su cosa cercare, non chi è.
        # `richiesta_categoria is None` esclude il turno che sta già
        # rispondendo a questa stessa domanda (vedi sopra): quello prosegue
        # nel flusso normale invece di tornare qui in loop.
        profilo_per_soglia = profile or _profile_from_slots(intent=intent, messaggio=message, filtri_esclusi=filtri_esclusi)
        if intent.kind is QuestionKind.AGEVOLAZIONE and _slot_anagrafici_dichiarati(
            profilo_per_soglia
        ) >= 2:
            indice_categoria = _indice_deterministico(message, len(_VARIANTI_RICHIESTA_CATEGORIA))
            return ChatAnswer(
                reply=_VARIANTI_RICHIESTA_CATEGORIA[indice_categoria],
                topic=intent.topic,
                kind=intent.kind,
                data_gap=None,
                needs_clarification=True,
                matches=[],
                spid_required=False,
                spid_reason=None,
            )
        nome_riferimento = scelto.nome if scelto is not None else "riferimento"
        indice_sconosciuto = _indice_deterministico(
            nome_riferimento, len(_VARIANTI_TOPIC_SCONOSCIUTO)
        )
        return ChatAnswer(
            reply=_VARIANTI_TOPIC_SCONOSCIUTO[indice_sconosciuto].format(
                comune=nome_riferimento
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
            intent=intent,
            records=records,
            comune_istat=comune_istat,
            parole=_parole_del_cittadino(message=message, storia=storia or []),
        )

    if not comune_coperto:
        # Il cittadino ha scelto un comune di cui non abbiamo i dati. Sul rail
        # delle agevolazioni non esiste un ripiego onesto: un'agevolazione
        # dipende da criteri che quel comune pubblica, e i criteri di un altro
        # comune non sono un'approssimazione — sono le regole di qualcun altro.
        # La lettura dal vivo non serve nemmeno come consolazione, perché
        # alimenterebbe un verdetto (D-01).
        nome = comune_per_codice(comune_istat)
        dove = nome.nome if nome is not None else "questo comune"
        return ChatAnswer(
            reply=(
                f"Di {dove} non abbiamo ancora letto i dati, quindi non posso dirti "
                "cosa ti spetta: le soglie e i requisiti li stabilisce il tuo comune, "
                "e quelli di un altro comune non valgono per te. Posso però dirti "
                "cosa pubblica il tuo, se mi chiedi di un ufficio o di un documento."
            ),
            topic=intent.topic,
            kind=QuestionKind.AGEVOLAZIONE,
            data_gap="not_published",
            needs_clarification=False,
            matches=[],
            spid_required=False,
            spid_reason=None,
        )

    if profile is not None and _e_cambio_persona(message):
        # D-56/R-LOGOUT: il cookie di sessione vince sempre — ma non in
        # silenzio quando il turno sembra parlare di un'altra persona.
        # Nessun reset automatico: si spiega e si chiede conferma, il
        # client azzera la sessione (`POST /api/session/dimentica` o
        # logout) SOLO dopo che il cittadino conferma.
        return ChatAnswer(
            reply=(
                "Sembra che tu stia chiedendo per un'altra persona, non per "
                "te. Per non mescolare i dati della sessione con quelli "
                "nuovi, prima devo mettere da parte quello che so già di te "
                "(età, ISEE, nucleo familiare, disabilità...). Confermi? "
                "Dopo la conferma puoi ripetere la domanda."
            ),
            topic=intent.topic,
            kind=intent.kind,
            data_gap="cambio_persona",
            needs_clarification=True,
            matches=[],
            spid_required=False,
            spid_reason=None,
        )

    active_profile = profile or _profile_from_slots(intent=intent, messaggio=message, filtri_esclusi=filtri_esclusi)

    if active_profile.disabilita_nucleo and active_profile.figli_minori is None:
        # D-53: il turno ha dichiarato un figlio con disabilita', ma non se
        # e' minorenne — e alcune agevolazioni (sull'eta') dipendono proprio
        # da questo. Si chiede, analogo a `_quale_comune`: nessuno stato
        # server nuovo, la risposta al turno dopo passa dal normale giro
        # slot (`figli_minori`/`figli_disabili`).
        return ChatAnswer(
            reply=(
                "Il figlio con disabilità che hai indicato è minorenne o "
                "maggiorenne? Alcune agevolazioni cambiano in base a questo."
            ),
            topic=intent.topic,
            kind=intent.kind,
            data_gap=None,
            needs_clarification=True,
            matches=[],
            spid_required=False,
            spid_reason=None,
        )

    # D-55: «tutte le categorie» abbandona il filtro per singolo topic (ogni
    # record del comune diventa candidato, esattamente come il ranker di
    # `GET /api/opportunities`, api.py:1333); una categoria scelta filtra ai
    # `Topic` di quella categoria PRIMA del ranking — mai dopo, o un record
    # ineleggibile di un'altra categoria potrebbe scavalcare uno pertinente.
    # Entrambe le vie sostituiscono, non affiancano, il candidates a singolo
    # topic: la classificazione del turno corrente resta quella su cui si
    # basa `intent.topic` per tutto il resto della risposta (spid/residenza).
    if richiesta_categoria == "tutte":
        # Le altre due vie passano da `_search_opportunities`, che toglie
        # le opportunità scadute (`_senza_scadute`, R-15): "tutte" deve
        # restare coerente con "utenze"/"mezzi"/"assegni" e col flusso a
        # singolo topic, non mostrare un bando scaduto solo perché nessun
        # filtro per topic è stato applicato.
        candidates = _senza_scadute(records)
    elif isinstance(richiesta_categoria, Categoria):
        visti: set[int] = set()
        candidates = []
        for topic_della_categoria in topics_di(richiesta_categoria):
            for opportunity in _search_opportunities(
                records=records, topic=topic_della_categoria
            ):
                if id(opportunity) not in visti:
                    visti.add(id(opportunity))
                    candidates.append(opportunity)
    else:
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


def _avvia_refresh_in_background(codice_istat: str) -> None:
    """Lancia `aggiorna_scansione` senza bloccare la risposta (D-S6).

    Fire-and-forget su un thread daemon: doppia-scansione occasionale, se due
    domande sullo stesso comune arrivano ravvicinate mentre il precedente
    refresh e' ancora in volo, e' accettata (DISCRETION, nessun lock). I dati
    mostrati in QUESTO turno restano quelli gia' in cache.
    """
    threading.Thread(
        target=aggiorna_scansione, args=(codice_istat,), daemon=True
    ).start()


def _scan_stato_per_comune(codice_istat: str | None) -> ScanStato | None:
    """Stato dello scan del comune riconosciuto, per il rail chat (D-S6).

    Scan assente o stantio (>6gg, `scansione_stantia`) -> il refresh parte in
    background e lo stato segnala `"aggiornamento_in_corso"`. Scan fresco ->
    nessun refresh, solo lo stato `"fresco"`. `None` se non c'e' un comune da
    guardare — sola lettura dello store, nessun tocco a matching/pesi/scala
    (D-S9).
    """
    if not codice_istat:
        return None
    record = carica_scansione(codice_istat)
    if record is None or scansione_stantia(record):
        _avvia_refresh_in_background(codice_istat)
        return ScanStato(
            stato="aggiornamento_in_corso",
            ultimo_scan=record.scansionato_il if record is not None else None,
        )
    return ScanStato(stato="fresco", ultimo_scan=record.scansionato_il)


async def _forse_aggiungi_bandi_live(
    risposta: ChatAnswer, *, codice_istat: str | None, message: str
) -> ChatAnswer:
    """KAPI 11 (gap-closure): additivo, non un reroute (D-01). Se il messaggio
    agevolazione usa un sinonimo civico di bando (`_BANDI_SINONIMI_RE`),
    allega ANCHE le card bandi live del comune alla risposta agevolazione
    gia' composta — senza toccarne il testo. Il ramo Topic.BANDI si popola
    gia' da se' (`_risposta_bandi`): qui e' un no-op se `bandi_live` e' gia'
    valorizzato, per non fare doppia scansione.

    Muto (nessun `bandi_live` allegato) se: nessun sinonimo nel messaggio,
    comune ignoto, o il comune non e' indirizzabile (`non_coperto` /
    `comune_ignoto` dall'esito) — una card senza bandi verificabili sarebbe
    solo rumore. `coperto_senza_bandi` invece SI' che si allega: e' l'esito
    onesto di una ricerca appena fatta, non un buco (memoria «Fonte Nuova non
    ha nulla da recuperare»).

    Degradazione onesta: qualunque eccezione nella scansione lascia la
    risposta agevolazione INTATTA, mai una 500 al cittadino.
    """
    if risposta.bandi_live is not None:
        return risposta
    if not _BANDI_SINONIMI_RE.search(message):
        return risposta
    if codice_istat is None or comune_per_codice(codice_istat) is None:
        return risposta
    try:
        esito = await asyncio.to_thread(bandi_live.bandi_arricchiti, codice_istat)
    except Exception:
        logger.warning(
            "bandi_arricchiti (scansione additiva) fallita per %s",
            codice_istat,
            exc_info=True,
        )
        return risposta
    if esito.esito in ("coperto_con_bandi", "coperto_senza_bandi"):
        return replace(risposta, bandi_live=esito)
    return risposta


#: Varianti deterministiche del follow-up "quanti figli?" (ciclo 12, B1):
#: stessa domanda, parole diverse — mai `random`, la demo resta riproducibile.
_DOMANDA_FIGLI_QUANTI = (
    "A proposito: quanti figli hai, e quanti anni hanno?",
    "Per essere precisi sul resto: quanti figli hai e quanti anni hanno?",
)

#: Varianti deterministiche del follow-up "e' minorenne?" (ciclo 12, B1) —
#: chiesto SOLO quando la disabilita' e' stata dichiarata (D-03).
_DOMANDA_DISABILE_MINORENNE = (
    "Una cosa in piu': la persona con disabilita' e' minorenne?",
    "Per capire bene: la persona con disabilita' e' minorenne?",
)

#: Varianti deterministiche del follow-up "chi c'e' in famiglia?" (ciclo 12,
#: gap-closure): fallback di ultima priorita', quando "famiglia"/"nucleo" e'
#: nominata ma nessuno slot concreto e' arrivato. Vincolo duro del
#: committente: la disabilita' non si nomina qui, mai — solo figli/eta'.
_DOMANDA_COMPOSIZIONE_FAMIGLIA = (
    "Raccontami chi c'e' nella tua famiglia: hai figli, e se si' di che eta'?",
    "Dimmi qualcosa in piu' sulla tua famiglia: hai figli, e quanti anni hanno?",
)

#: "Famiglia"/"nucleo" nominati in modo generico (nessun numero agganciato).
#: "Famiglia di 4"/"nucleo di 4"/"siamo in 4" sono gia' un NUCLEO_FAMILIARE
#: concreto — quel ramo lo riconosce `riconosci_filtri` (`filtri.py`), qui si
#: esclude esplicitamente per non doppio-leggere lo stesso dato (D-03).
_FAMIGLIA_GENERICA_RE = re.compile(r"\bnucleo\s+familiare\b|\bfamiglia\b|\bnucleo\b", re.IGNORECASE)


def menziona_famiglia_generica(message: str) -> bool:
    """Vero se `message` nomina "famiglia"/"nucleo" senza un numero concreto.

    Non e' un nuovo riconoscitore di filtri (D-03): non produce nessun
    `Filtro`, nessun valore — serve solo a decidere se vale la pena chiedere.
    Riusa `riconosci_filtri` (`treasureiq.chat.filtri`) per escludere il caso
    in cui il testo e' gia' concreto ("famiglia di 4"), invece di reinventare
    il pattern qui.

    AM-1 (hard): legge solo l'argomento passato. Il chiamante (`_forse_chiedi_
    chiarimento`) ci passa sempre `message`, mai `storia`.
    """
    if not message:
        return False
    if _FAMIGLIA_GENERICA_RE.search(message) is None:
        return False
    from treasureiq.chat.filtri import FiltroChiave, riconosci_filtri  # import locale: circolare

    return not any(f.chiave == FiltroChiave.NUCLEO_FAMILIARE for f in riconosci_filtri(message))


def _forse_chiedi_chiarimento(
    risposta: ChatAnswer,
    *,
    storia: list[str] | None,
    message: str,
    filtri_accumulati: dict | None,
) -> ChatAnswer:
    """Accoda al massimo UNA domanda di follow-up al turno (ciclo 12, B1).

    Additiva, mai bloccante (D-04): la risposta di merito in `risposta.reply`
    resta intera, la domanda si accoda in coda. `needs_clarification` non
    viene toccato — il chiarimento viaggia nel campo dedicato.

    AM-1 (hard): il trigger legge SOLO `message`, mai `storia`. Chi ha detto
    "ho figli" un turno fa e non ha mai risposto non viene rincorso ai turni
    successivi — un solo tentativo, nel turno in cui la dichiarazione arriva.
    `storia` resta nella firma solo per simmetria con gli altri hook di
    `build_chat_answer` (non e' letta per decidere se chiedere).
    """
    del storia  # AM-1: deliberatamente non usato nel trigger.
    from treasureiq.chat.filtri import (  # import locale: filtri.py importa respond.py
        FiltroChiave,
        dichiarazione_figli_senza_numero,
        riconosci_filtri,
    )

    accumulati = filtri_accumulati or {}

    if dichiarazione_figli_senza_numero(message) and FiltroChiave.FIGLI_MINORI not in accumulati:
        domanda = _DOMANDA_FIGLI_QUANTI[_indice_deterministico(message, len(_DOMANDA_FIGLI_QUANTI))]
        return replace(
            risposta,
            reply=f"{risposta.reply}\n\n{domanda}",
            chiarimento="figli_quanti",
        )

    # D-03: mai proattivo. La disabilita' deve essere dichiarata nel turno
    # corrente (stessa lettura deterministica di `riconosci_filtri`, nessuna
    # inferenza nuova) — non basta che sia nota da un turno precedente.
    disabilita_dichiarata_ora = any(
        f.chiave in (FiltroChiave.DISABILITA, FiltroChiave.DISABILITA_NUCLEO)
        for f in riconosci_filtri(message)
    )
    if disabilita_dichiarata_ora and FiltroChiave.DISABILITA_NUCLEO not in accumulati:
        domanda = _DOMANDA_DISABILE_MINORENNE[
            _indice_deterministico(message, len(_DOMANDA_DISABILE_MINORENNE))
        ]
        return replace(
            risposta,
            reply=f"{risposta.reply}\n\n{domanda}",
            chiarimento="disabile_minorenne",
        )

    # Ultima priorita' (gap-closure): "famiglia"/"nucleo" nominata in modo
    # generico, senza NESSUNO slot concreto sulla famiglia gia' noto. Chi ha
    # gia' detto "ho figli" o "famiglia di 4" e' finito in uno dei due rami
    # sopra e non arriva qui — questo e' il fallback per chi non ha detto
    # nulla di concreto. Vincolo duro: mai nominare la disabilita'.
    slot_famiglia_concreto = any(
        chiave in accumulati
        for chiave in (
            FiltroChiave.FIGLI_MINORI,
            FiltroChiave.NUCLEO_FAMILIARE,
            FiltroChiave.DISABILITA,
            FiltroChiave.DISABILITA_NUCLEO,
        )
    )
    if not slot_famiglia_concreto and menziona_famiglia_generica(message):
        domanda = _DOMANDA_COMPOSIZIONE_FAMIGLIA[
            _indice_deterministico(message, len(_DOMANDA_COMPOSIZIONE_FAMIGLIA))
        ]
        return replace(
            risposta,
            reply=f"{risposta.reply}\n\n{domanda}",
            chiarimento="composizione_famiglia",
        )

    return risposta


async def build_chat_answer(
    *,
    message: str,
    profile: CitizenProfile | None,
    records: list[Opportunity],
    storia: list[str] | None = None,
    comune_istat: str | None = None,
    comune_coperto: bool = True,
    today: date | None = None,
    filtri_esclusi: frozenset | None = None,
    filtri_accumulati: dict | None = None,
) -> ChatAnswer:
    """Compone la risposta, e se il comune non e' coperto lo dice **in testa**.

    L'avviso sta davanti al resto e non al posto del resto. Fermarsi al «non
    copro il tuo comune» e' onesto sulla fonte e inutile per chi ha fatto la
    domanda: nasconde le misure nazionali e regionali, che valgono comunque.

    Il caso che ha prodotto questo guscio: una persona di Sant'Orsola Terme
    chiedeva dei mezzi pubblici e riceveva un rifiuto, mentre in archivio
    c'era «Agevolazioni tariffarie regionali per il trasporto pubblico».

    La decisione sta qui e non dentro `_componi_risposta` perche' riguarda
    *quali fonti* si guardano, non *come* si risponde — e perche' la funzione
    interna ha sei punti di uscita, ognuno dei quali avrebbe dovuto
    ricordarsi di anteporre la stessa frase.
    """
    candidati = _comuni_candidati(message)
    if len(candidati) >= 2:
        # D-54: prima l'ambiguita' spariva dentro `_comune_nominato` (tornava
        # `None`, come se nessun comune fosse stato nominato) e «vivo a
        # Pergine» finiva silenziosamente sul comune del profilo. `_quale_comune`
        # esisteva gia' mai collegata (dead code): la si cablava qui, prima del
        # ramo fuori-copertura, cosi' la domanda parte prima di decidere quali
        # record guardare.
        #
        # Se pero' l'utente ha gia' scelto da una scheda, `comune_istat` porta
        # l'istat di UNO di questi candidati: la scelta e' fatta, non si richiede.
        # Vale solo se l'istat e' tra i candidati del testo — un `comune_istat`
        # di profilo (Albano) su una domanda ambigua altrui («figline») non conta
        # come scelta, e si continua a chiedere.
        scelto = (
            next((c for c in candidati if c.codice_istat == comune_istat), None)
            if comune_istat
            else None
        )
        if scelto is None:
            provider: LLMProvider = load_provider(role="chat")
            intent = await extract_intent(message=message, provider=provider, storia=storia)
            return _quale_comune(candidati, intent)
        nominato = scelto
    else:
        nominato = candidati[0] if candidati else None
    # Il comune puo' arrivare senza essere ridigitato in QUESTO turno: una
    # domanda di follow-up («bonus per aprire ditte?») porta il comune dal
    # profilo via `comune_istat`, non dal testo. Se quel comune non lo
    # leggiamo, vale lo stesso ramo del comune nominato — premessa
    # fuori-copertura + ricerca live — altrimenti la lettura dal vivo scattava
    # solo se il cittadino riscriveva il nome del comune a ogni domanda, e chi
    # aveva gia' scelto Bisceglie si sentiva dire «non c'e' nulla» senza che
    # nessuno avesse guardato.
    if nominato is None and comune_istat and not comune_coperto:
        nominato = comune_per_codice(comune_istat)
    regione = _regione_del_cittadino(nominato=nominato, comune_istat=comune_istat)
    # Una misura regionale di un'altra regione non riguarda chi fa la domanda,
    # e vale anche quando il suo comune lo leggiamo: prima questo filtro
    # scattava solo fuori copertura, e un residente a Benevento si vedeva
    # offrire un'agevolazione della Regione Lazio.
    records = _senza_regioni_altrui(records, regione=regione)
    if nominato is not None and nominato.codice_istat not in load_enti():
        risposta = await _componi_risposta(
            message=message, profile=profile, storia=storia, today=today,
            records=_solo_sovracomunali(records, regione=nominato.regione),
            comune_istat=None,
            comune_coperto=False,
            filtri_esclusi=filtri_esclusi,
            # I records/naming agevolazione restano fuori-copertura (comune_istat
            # None), ma la scansione bandi deve puntare al comune del cittadino
            # (`nominato`), non al DEFAULT Albano. Bug Bisceglie→Albano.
            comune_bandi_istat=nominato.codice_istat,
        )
        # `ChatAnswer` e' una dataclass, non un modello pydantic: si copia con
        # `replace`, non con `model_copy`.
        risposta = _prova_live(risposta=risposta, comune=nominato, message=message)
        # A ricerca fatta, chiediamo anche se questo comune sarebbe raggiungibile
        # dal connettore AgID: cosi' la risposta non ripiega in silenzio sulla
        # sola ricerca web quando il portale e' strutturato e indirizzabile.
        # Sonda muta: se fallisce, `connettore` resta None e nulla cambia.
        connettore = sonda_connettore(nominato.codice_istat)
        # Recuperiamo i recapiti al volo, senza chiederlo: non e' una risposta
        # di TreasureIQ, e' il biglietto da visita del comune. Va nel pannello a
        # sinistra come «numeri utili», con fonte e data del controllo. Muto:
        # se lo scrape non trova nulla, `numeri_utili` resta None.
        numeri = _numeri_utili_al_volo(nominato.codice_istat)
        # La coda di `_componi_risposta` e' un vicolo cieco («non sono riuscito a
        # collegare... rivolgiti all'URP»): ha senso quando NON abbiamo cercato,
        # ma contraddice la premessa quando la ricerca live ha trovato pagine —
        # «qui sotto trovi quello che ho visto» e subito dopo «non ho trovato
        # niente». Se le pagine ci sono, la premessa basta e la coda si toglie;
        # una domanda-chiarimento (con «?») resta, non e' un vicolo cieco.
        trovate_live = (
            risposta.info is not None
            and risposta.info.letto_dal_vivo
            and bool(risposta.info.web_results)
        )
        vicolo_cieco = getattr(risposta, "data_gap", None) == "none_found"
        # La coda si toglie anche nel vicolo cieco: la premessa «Attenzione» la
        # riscrive per intero. Resta solo se e' una domanda-chiarimento («?»).
        coda = "" if ((trovate_live or vicolo_cieco) and "?" not in risposta.reply) else risposta.reply
        # BANDI con esito live gia' composto (`_risposta_bandi`) ha gia' un
        # reply onesto (coperto/non coperto, advocacy inclusa): la premessa
        # "fuori copertura" generica lo sovrascriverebbe e butterebbe via il
        # testo corretto pur lasciando `bandi_live` intatto sull'oggetto.
        if risposta.topic is Topic.BANDI and risposta.bandi_live is not None:
            reply = risposta.reply
        else:
            premessa = _premessa_fuori_copertura(
                nominato, risposta, connettore, ha_scheda_laterale=numeri is not None
            )
            reply = premessa + ("\n\n" + coda if coda else "")
        risposta = replace(
            risposta,
            reply=reply,
            connettore=connettore,
            numeri_utili=numeri,
            scan=_scan_stato_per_comune(nominato.codice_istat),
        )
        # KAPI 11 (gap-closure): scansione bandi additiva su sinonimo civico,
        # additiva alla risposta agevolazione fuori-copertura (D-01, no reroute).
        risposta = await _forse_aggiungi_bandi_live(
            risposta, codice_istat=nominato.codice_istat, message=message
        )
        # KAPI 12 (B1): follow-up slot additivo, sempre l'ultimo aggancio.
        return _forse_chiedi_chiarimento(
            risposta, storia=storia, message=message, filtri_accumulati=filtri_accumulati
        )
    risposta = await _componi_risposta(
        message=message,
        profile=profile,
        storia=storia,
        today=today,
        records=records,
        comune_istat=comune_istat,
        comune_coperto=comune_coperto,
        filtri_esclusi=filtri_esclusi,
    )
    # Un comune coperto ma con seed magro puo' rispondere «non ho trovato nulla»
    # pur essendo indirizzabile dal connettore AgID (servizi + bandi live). Prima
    # cadeva sul vicolo cieco nudo verso l'URP: ora offriamo la stessa lettura
    # live del ramo fuori-copertura — mappa servizi, bandi, numeri utili, premessa
    # onesta. Navigazione, nessun verdetto (D-01). Solo se il portale e'
    # davvero indirizzabile, altrimenti la coda originale resta.
    # Il comune puo' arrivare dal testo (`nominato`, gia' estratto sopra) anche
    # quando la scheda non ha passato un `comune_istat` esplicito: la rotta passa
    # `body.comune_istat` grezzo, che e' None quando il comune viene dal chip di
    # profilo e non da una scelta. Il ripiego live vale in entrambi i casi, come
    # nel ramo fuori-copertura che chiave su `nominato`, non su `comune_istat`.
    comune = nominato or (comune_per_codice(comune_istat) if comune_istat else None)
    if getattr(risposta, "data_gap", None) == "none_found" and comune is not None:
        connettore = sonda_connettore(comune.codice_istat)
        if connettore is not None and connettore.indirizzabile:
            numeri = _numeri_utili_al_volo(comune.codice_istat)
            coda = "" if "?" not in risposta.reply else risposta.reply
            premessa = _premessa_fuori_copertura(
                comune, risposta, connettore, ha_scheda_laterale=numeri is not None
            )
            reply = premessa + ("\n\n" + coda if coda else "")
            risposta = replace(
                risposta,
                reply=reply,
                connettore=connettore,
                numeri_utili=numeri,
                scan=_scan_stato_per_comune(comune.codice_istat),
            )
            # KAPI 11 (gap-closure): stesso attacco additivo del ramo (B).
            risposta = await _forse_aggiungi_bandi_live(
                risposta, codice_istat=comune.codice_istat, message=message
            )
            # KAPI 12 (B1): follow-up slot additivo, sempre l'ultimo aggancio.
            return _forse_chiedi_chiarimento(
                risposta, storia=storia, message=message, filtri_accumulati=filtri_accumulati
            )
    risposta = replace(
        risposta,
        # Comune coperto: mettiamo a sinistra il suo biglietto da visita —
        # recapiti dallo store, non uno scrape live (D-S4). Muto se assenti.
        numeri_utili=(
            _numeri_utili_da_store(comune.codice_istat) if comune is not None else None
        ),
        scan=_scan_stato_per_comune(comune.codice_istat if comune is not None else None),
    )
    # KAPI 11 (gap-closure): comune coperto "normale" — stesso attacco additivo.
    risposta = await _forse_aggiungi_bandi_live(
        risposta,
        codice_istat=comune.codice_istat if comune is not None else None,
        message=message,
    )
    # KAPI 12 (B1): follow-up slot additivo, sempre l'ultimo aggancio.
    return _forse_chiedi_chiarimento(
        risposta, storia=storia, message=message, filtri_accumulati=filtri_accumulati
    )


def _regione_del_cittadino(*, nominato, comune_istat: str | None) -> str | None:
    """La regione di chi fa la domanda, dal comune nominato o dal profilo."""
    if nominato is not None and getattr(nominato, "regione", None):
        return nominato.regione
    if comune_istat:
        suo = comune_per_codice(comune_istat)
        if suo is not None:
            return suo.regione
    return None


def _senza_regioni_altrui(records, *, regione: str | None):
    """Toglie le misure regionali di regioni diverse dalla propria.

    Se non sappiamo dove abita la persona non togliamo niente: nascondere una
    misura che potrebbe spettarle e' peggio che mostrargliene una che non la
    riguarda, purche' l'ente che la pubblica sia scritto sulla scheda.
    """
    if not regione:
        return records
    mia = regione.strip().casefold()
    tenuti = []
    for r in records:
        if r.livello is Livello.REGIONALE:
            sua = (getattr(r, "regione", None) or "").strip().casefold()
            if sua and sua != mia:
                continue
        tenuti.append(r)
    return tenuti


def _regione_del_cittadino(*, nominato, comune_istat: str | None) -> str | None:
    """La regione di chi fa la domanda, dal comune nominato o dal profilo."""
    if nominato is not None and getattr(nominato, "regione", None):
        return nominato.regione
    if comune_istat:
        suo = comune_per_codice(comune_istat)
        if suo is not None:
            return suo.regione
    return None


def _senza_regioni_altrui(records, *, regione: str | None):
    """Toglie le misure regionali di regioni diverse dalla propria.

    Se non sappiamo dove abita la persona non togliamo niente: nascondere una
    misura che potrebbe spettarle e' peggio che mostrarne una che non la
    riguarda, visto che l'ente che la pubblica e' scritto sulla scheda.
    """
    if not regione:
        return records
    mia = regione.strip().casefold()
    tenuti = []
    for r in records:
        if r.livello is Livello.REGIONALE:
            sua = (getattr(r, "regione", None) or "").strip().casefold()
            if sua and sua != mia:
                continue
        tenuti.append(r)
    return tenuti


def _solo_sovracomunali(records, *, regione: str | None):
    """Le misure che valgono anche senza leggere il comune del cittadino.

    Cadono quelle comunali, perche' sono di un altro comune. Ma cade anche una
    misura **regionale di un'altra regione**: offrire un'agevolazione del Lazio
    a chi vive in Trentino e' esattamente l'errore che abbiamo appena chiuso
    sui comuni, con un'etichetta piu' grande davanti.

    Restano sempre le nazionali, che non dipendono da dove si abita.
    """
    tenuti = []
    for r in records:
        if r.livello is Livello.COMUNALE:
            continue
        if r.livello is Livello.REGIONALE:
            sua = (getattr(r, "regione", None) or "").strip().casefold()
            if sua and regione and sua != regione.strip().casefold():
                continue
        tenuti.append(r)
    return tenuti


def _comuni_candidati(message: str) -> list:
    """I comuni compatibili col messaggio, prima di decidere se sceglierne uno.

    Stessa precedenza di `_comune_nominato`: il confronto esatto sui 7.896
    comuni vince su tutto (se risolve, il candidato e' uno solo per
    definizione); solo se non risolve entra il confronto per parola-nel-nome.
    Serve a chi, a differenza di `_comune_nominato`, ha bisogno di sapere
    QUANTI candidati ci sono per decidere se chiedere quale (D-54): prima
    l'ambiguita' spariva qui dentro, ora la si porta fuori.
    """
    # Le parole-non-toponimo vanno tolte PRIMA anche del confronto esatto: «minori»
    # e' una chiave esatta dell'indice (Minori, SA), quindi senza ripulire qui il
    # match esatto vince e la sottrazione dentro `_comuni_che_iniziano_per` non
    # entra nemmeno in gioco. Tolgo le parole intere, non i pezzi: «gorla minore»
    # resta «gorla» e risolve ancora il nome intero per prefisso.
    ripulito = " ".join(
        p
        for p in (message or "").split()
        if p.strip(".,;:!?'\"").lower() not in _PAROLE_NON_TOPONIMI
    )
    esatto = risolvi_comune(ripulito)
    if esatto is not None:
        return [esatto]
    return _comuni_che_iniziano_per(ripulito)


def _comune_nominato(message: str):
    """Il comune che il cittadino ha nominato, se se ne riconosce uno solo.

    Prima il confronto esatto sui 7.896 comuni, poi quello per prefisso —
    «sono di pergine» non risolveva perche' il confronto esatto vuole il nome
    intero. Con piu' candidati non sceglie: torna `None`, e la risposta
    prosegue come se nessun comune fosse stato nominato.

    Chi ha bisogno di sapere QUANTI candidati ci sono (per chiedere quale
    invece di ignorare l'ambiguita', D-54) usa `_comuni_candidati` e non
    questa funzione: qui il collasso a `None` resta intenzionale per i
    chiamanti che vogliono solo "un comune o niente".
    """
    candidati = _comuni_candidati(message)
    return candidati[0] if len(candidati) == 1 else None
