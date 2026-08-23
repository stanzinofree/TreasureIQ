"""Intent + slot extraction from a citizen's free-text chat message.

This is job (a) of the two the runtime model is trusted with (see
`.kapi/spec.md` D-01): map free Italian text onto a *closed* schema. The
model never returns prose here, and `Topic` is a fixed enum rather than a
free string precisely so a wrong classification is a wrong *label*, never a
fabricated fact — the citizen's own text never becomes something quoted back
to them or fed into an eligibility decision. `match/engine.py` still owns
every verdict; this module only decides which opportunities are worth
running through it, and with which anagraphic slots.

`TOPIC_KEYWORDS` is the deterministic bridge between a topic and the
Albano seed data: it drives a plain substring search in
`treasureiq.chat.respond`, not the model. Keeping the search keyword-based
and outside the model keeps the retrieval step auditable.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from treasureiq.chat.intent_scorer import score_intent
from treasureiq.extract.providers import LLMProvider
from treasureiq.schema import EmploymentStatus

logger = logging.getLogger(__name__)


class Topic(str, Enum):
    """A closed vocabulary of civic topics the chat can recognise.

    Built from what is actually present in the Albano seed (see
    `.kapi/discover/codebase-map.md`), plus `SOSTEGNO_UTENZE` for the demo's
    canonical "bolletta troppo alta" question — a legitimate civic concern
    that the comune's data simply does not cover. That gap is exactly the
    `not_published` case D-05/D-09 spell out: recognising the topic and
    still finding nothing is a different situation from not understanding
    the question at all (`SCONOSCIUTO`).
    """

    TRASPORTO_SCOLASTICO = "trasporto_scolastico"
    #: Abbonamenti e agevolazioni sul trasporto pubblico locale. Distinto dallo
    #: scuolabus: chi chiede «bandi per i mezzi pubblici» non sta chiedendo del
    #: pulmino della scuola, e senza questa voce non agganciava niente.
    TRASPORTO_PUBBLICO = "trasporto_pubblico"
    MENSA_SCOLASTICA = "mensa_scolastica"
    CONTRIBUTO_LIBRI = "contributo_libri"
    BORSA_STUDIO = "borsa_studio"
    VOUCHER_CONCILIAZIONE = "voucher_conciliazione"
    ASSEGNO_MATERNITA = "assegno_maternita"
    CONTRIBUTO_AFFITTO = "contributo_affitto"
    SOSTEGNO_UTENZE = "sostegno_utenze"
    ASSISTENZA_DISABILITA = "assistenza_disabilita"
    CONTRASSEGNO_DISABILI = "contrassegno_disabili"
    ANAGRAFE_CARTA_IDENTITA = "anagrafe_carta_identita"
    ACCESSO_ATTI = "accesso_atti"
    OCCUPAZIONE_SUOLO = "occupazione_suolo"
    CAREGIVER_DOMICILIARE = "caregiver_domiciliare"
    MATRIMONIO_SEPARAZIONE = "matrimonio_separazione"
    INCLUSIONE_SOCIALE = "inclusione_sociale"
    SUAP_IMPRESE = "suap_imprese"
    AREA_VERDE = "area_verde"
    RIFIUTI = "rifiuti"
    VOLONTARIATO = "volontariato"
    #: IMU, TARI, ufficio tributi. Riconosciuto anche se il seed di Albano non
    #: lo copre: un cittadino che chiede dell'ufficio tributi ha fatto una
    #: domanda civica legittima, e senza questa voce il modello la mappava sul
    #: topic superstite più vicino — l'anagrafe — rispondendo con la pagina
    #: sbagliata invece che con «non risulta pubblicato».
    TRIBUTI = "tributi"
    #: Bandi e avvisi pubblici letti dal vivo da Amministrazione Trasparente
    #: (KAPI 7, bandi-live-agid), non dallo snapshot ingerito: un cittadino
    #: che chiede «che bandi ci sono?» aspetta un elenco aggiornato ad ora,
    #: non l'ultima fotografia dell'ingestione. Attenzione alla guardia in
    #: `extract_intent`: «bandi per i mezzi pubblici» nomina "bandi" ma parla
    #: di TRASPORTO_PUBBLICO, non di un elenco di avvisi.
    BANDI = "bandi"
    #: Modulistica e servizi online del comune (Ramo 3). Il cittadino chiede
    #: «dove faccio la pratica / il modulo per X» e la risposta è un accesso,
    #: non un elenco: modulo informativo, modulo scaricabile o servizio
    #: autenticato. Il PRIMO incremento SP cabla solo il portale servizi
    #: (servizio autenticato): TIQ indica la porta ufficiale e non entra mai
    #: (D-R3-5). Il tipo di accesso è un ESITO dei dati trovati, non una scelta
    #: iniziale del cittadino (D-R3-1).
    MODULISTICA = "modulistica"
    #: The model could not map the message onto any of the above. Never
    #: guessed into just to avoid this value — see the system prompt.
    SCONOSCIUTO = "sconosciuto"


class BeneficiaryRole(str, Enum):
    """Who the INFORMAZIONE answer is actually for, for the small set of
    topics where that changes what gets retrieved (D-19 round 2, R-9).

    Some topics conflate two different citizens under one word: "cerco un
    servizio di volontariato per anziani" could be an elderly person asking
    for help (`ASSISTITO`) or someone offering to volunteer to help the
    elderly (`VOLONTARIO`) — the answer lives in a different set of
    documents either way (`servizi sociali` vs `volontariato`). Two values
    are enough; no speculative taxonomy. Stays `None` unless the citizen
    states it explicitly — never inferred from a topic word like "anziani"
    alone (R-9: an unstated role stays unset and gets asked about, never
    guessed).
    """

    ASSISTITO = "assistito"
    VOLONTARIO = "volontario"


class QuestionKind(str, Enum):
    """The *shape* of the citizen's question, classified before topic (D-19).

    `AGEVOLAZIONE`: the citizen is asking whether they are entitled to
    something — a benefit, a discount, a contribution — and expects a
    verdict from `match/engine.py`. `INFORMAZIONE`: the citizen wants a
    civic fact (a schedule, a service, an office) with no eligibility
    question attached. Defaults to `AGEVOLAZIONE` on model failure — the
    existing rail — never crashes (see `extract_intent`).
    """

    AGEVOLAZIONE = "agevolazione"
    INFORMAZIONE = "informazione"


#: Deterministic keyword sets used by `treasureiq.chat.respond` to filter the
#: seed for a recognised topic. Plain lowercase substring matching — no model
#: involved in this step, so it stays auditable and cheap.
TOPIC_KEYWORDS: dict[Topic, tuple[str, ...]] = {
    Topic.TRASPORTO_SCOLASTICO: ("trasporto scolastico", "scuolabus"),
    Topic.TRASPORTO_PUBBLICO: (
        "trasporto pubblico",
        "mezzi pubblici",
        "abbonamento",
        "autobus",
        "tpl",
        "metropolitana",
    ),
    Topic.MENSA_SCOLASTICA: ("mensa",),
    Topic.CONTRIBUTO_LIBRI: ("libri di testo", "sussidi didattici", "libri scolastici"),
    Topic.BORSA_STUDIO: ("borsa di studio", "iostudio"),
    Topic.VOUCHER_CONCILIAZIONE: (
        "voucher",
        "conciliazione vita-lavoro",
        "asilo nido",
        "centro estivo",
    ),
    Topic.ASSEGNO_MATERNITA: ("maternit-", "gravidanza", "permesso rosa"),
    Topic.CONTRIBUTO_AFFITTO: ("affitto", "locazione", "canone di locazione", "sfratto"),
    Topic.SOSTEGNO_UTENZE: (
        "bolletta",
        "bollette",
        "energia elettrica",
        "utenza elettrica",
        "fornitura elettrica",
        "bonus sociale",
        "luce e gas",
        # Bare "utenze" and bare "gas" are deliberately absent. Retrieval here
        # is plain substring matching, and both words carry a second, unrelated
        # sense in municipal prose: waste-collection pages count "utenze
        # domestiche" (the households served, not their bills), which is enough
        # to pull "Raccolta differenziata" into an answer about an electricity
        # bill. The specific phrases above still reach every record that is
        # genuinely about utility costs — "Bonus sociale bollette (energia
        # elettrica, gas, servizio idrico)" matches on three of them.
    ),
    Topic.ASSISTENZA_DISABILITA: ("disabilit-", "alzheimer", "assistenza domiciliare"),
    Topic.CONTRASSEGNO_DISABILI: ("contrassegno disabili", "permesso disabili"),
    Topic.ANAGRAFE_CARTA_IDENTITA: ("carta d'identit", "carta identit", "anagrafe"),
    Topic.ACCESSO_ATTI: ("accesso agli atti", "atti amministrativi"),
    Topic.OCCUPAZIONE_SUOLO: ("occupazione suolo", "suolo pubblico"),
    Topic.CAREGIVER_DOMICILIARE: ("caregiver", "assistenza domiciliare"),
    Topic.MATRIMONIO_SEPARAZIONE: ("matrimonio", "separazione", "divorzio"),
    Topic.INCLUSIONE_SOCIALE: ("inclusione sociale", "hermes"),
    Topic.SUAP_IMPRESE: ("suap", "attività produttive", "impresa"),
    Topic.AREA_VERDE: ("area verde", "adotta un'area"),
    Topic.RIFIUTI: (
        "rifiuti",
        "vetro",
        "raccolta differenziata",
        "calendario raccolta",
        "porta a porta",
        "isola ecologica",
    ),
    Topic.VOLONTARIATO: (
        "volontariato",
        "volontario",
        "anziani",
        "associazioni",
        "servizio civile",
    ),
    Topic.TRIBUTI: (
        "tributi",
        "imu",
        "tari",
        "tassa rifiuti",
        "tassa sui rifiuti",
        "tasse comunali",
        "imposta municipale",
    ),
    #: §5.4 pinnate: NON aggiungere "trasporto" o "mezzi" qui — sono di
    #: TRASPORTO_PUBBLICO, e la guardia in `extract_intent`
    #: (`_e_bando_di_trasporto_pubblico`) si aspetta gli insiemi disgiunti.
    Topic.BANDI: ("bando", "bandi", "avviso pubblico", "avvisi pubblici", "graduatoria"),
    #: Modulistica e servizi online (Ramo 3). Frasi che segnalano l'intento di
    #: fare una pratica online o procurarsi un modulo, distinte dai bandi:
    #: "sportello telematico"/"servizi online" indicano il portale autenticato,
    #: "modulo per"/"modulistica" il modulo pubblico. Substring lowercase, come
    #: le altre voci — nessun modello in questo passo.
    Topic.MODULISTICA: (
        "modulistica",
        "modulo per",
        "sportello telematico",
        "sportello online",
        "servizi online",
        "servizio online",
        "area personale",
        "domanda online",
        "istanza online",
    ),
    Topic.SCONOSCIUTO: (),
}


#: Topics where the *role* of the citizen (recipient vs. volunteer) points
#: at genuinely different documents, keyed to the role-specific keyword set
#: `treasureiq.chat.respond` searches with instead of `TOPIC_KEYWORDS` once
#: the role is known. Small and explicit on purpose (per D-19 round 2): a
#: topic like `RIFIUTI` never grows a role question because collection days
#: do not depend on who is asking.
AMBIGUOUS_ROLE_TOPICS: dict[Topic, dict[BeneficiaryRole, tuple[str, ...]]] = {
    Topic.VOLONTARIATO: {
        BeneficiaryRole.ASSISTITO: ("anziani",),
        BeneficiaryRole.VOLONTARIO: (
            "volontariato",
            "volontario",
            "associazioni",
            "servizio civile",
        ),
    },
}


#: Topics that are informational *by their nature*, regardless of how the
#: citizen phrased the question — mirrors `AMBIGUOUS_ROLE_TOPICS`'s idiom: a
#: property of the topic, not a per-message judgment call. `RIFIUTI` (waste
#: collection schedules) and `VOLONTARIATO` (volunteering) have no
#: eligibility criteria to evaluate — there is no verdict `match/engine.py`
#: could ever produce for them. `qwen3:4b` (R-8) still reads "voglio fare
#: volontariato" as a benefit request because of the verb, so `kind` is not
#: trusted from the model for these topics: `extract_intent` overrides it to
#: `INFORMAZIONE` deterministically, the same remedy already used for
#: `beneficiary_role`. Deliberately small: a topic like
#: `TRASPORTO_SCOLASTICO` genuinely can be either an information request or
#: a benefit request and must stay the model's call — it is NOT in this set.
INFORMATIONAL_BY_NATURE_TOPICS: frozenset[Topic] = frozenset(
    {Topic.RIFIUTI, Topic.VOLONTARIATO}
)


#: Deterministic substring markers gating `ChatIntent.beneficiary_role`,
#: mirroring `TOPIC_KEYWORDS`'s idiom. `qwen3:4b` (R-8) sometimes echoes a
#: role back from a bare topic word ("volontariato", "anziani") even though
#: the system prompt says not to — small models are unreliable at exactly
#: this kind of negative instruction. So the model's `beneficiary_role`
#: claim is trusted only when the citizen's own raw text contains a marker
#: that actually states it; otherwise `_confirm_beneficiary_role` discards
#: it. This is the R-9 guard made structural rather than left to the
#: model's discipline alone.
BENEFICIARY_ROLE_MARKERS: dict[BeneficiaryRole, tuple[str, ...]] = {
    BeneficiaryRole.ASSISTITO: ("per me", "sono io"),
    BeneficiaryRole.VOLONTARIO: (
        "fare volontariato",
        "offrirmi come volontario",
        "offrirmi come volontaria",
        "dare una mano",
        "voglio aiutare",
        "mi offro",
    ),
}


#: Marcatori per la dichiarazione ESPLICITA del sesso ("sono una donna"), lo
#: stesso idioma di `BENEFICIARY_ROLE_MARKERS`: un valore che il modello ha
#: prodotto e' fidato solo se le parole del cittadino lo confermano per
#: davvero (R-9), altrimenti puo' essere un'eco della storia (D-47/anti-leak).
_SESSO_MARKERS: dict[Literal["f", "m"], tuple[str, ...]] = {
    "f": ("sono una donna", "sono donna"),
    "m": ("sono un uomo", "sono uomo"),
}

#: «figlio disabile», «mia figlia con disabilità»: la stessa idea, per la
#: dichiarazione di un figlio con disabilita' nel nucleo (D-53).
_FIGLIO_DISABILE_MARKERS: tuple[str, ...] = (
    "figlio disabile",
    "figlia disabile",
    "figli disabili",
    "figlie disabili",
    "figlio con disabilit",
    "figlia con disabilit",
    "figlio è disabile",
    "figlia è disabile",
)


def _sesso_dichiarato_nel_testo(messaggio: str) -> Literal["f", "m"] | None:
    """Il sesso dichiarato esplicitamente in QUESTO messaggio, non nella
    storia. Non e' la deduzione dal nome (`chat.nomi_genere.sesso_da_nome`,
    deterministica e chiamata altrove): qui si controlla solo la frase
    esplicita ("sono una donna"/"sono un uomo") che il modello puo' aver
    letto, per confermarla o scartarla come `_confirm_beneficiary_role` fa
    per il ruolo."""
    if not messaggio:
        return None
    haystack = messaggio.casefold()
    for valore, marcatori in _SESSO_MARKERS.items():
        if any(marcatore in haystack for marcatore in marcatori):
            return valore
    return None


def _figlio_disabile_dichiarato_nel_testo(messaggio: str) -> bool:
    """Se QUESTO messaggio dichiara davvero un figlio con disabilita', non
    se il modello l'ha solo riletto da un turno precedente."""
    if not messaggio:
        return False
    haystack = messaggio.casefold()
    return any(marcatore in haystack for marcatore in _FIGLIO_DISABILE_MARKERS)


#: La disabilita' della persona di cui si parla — se stessi («sono disabile»)
#: o il beneficiario di cui si chiede in terza persona («mia madre e'
#: disabile»). E' `disabilita`, non `disabilita_nucleo`: quest'ultima e' del
#: figlio e la si riconosce a parte. Era l'unico slot anagrafico lasciato al
#: solo modello: qwen3:4b lo mancava e il profilo usciva senza, pur avendolo
#: scritto il cittadino.
#: Le parole con cui il cittadino nomina una disabilita': «disabile»,
#: «disabili», «disabilità», «invalido/a/i», «invalidità», «handicap». Le
#: chiusure sono esplicite (non `\w*`) di proposito, cosi' «disabilitato/a»
#: — un servizio disattivato, non una persona — non ci cade dentro. Il
#: confine di parola prende «disabile» anche nudo: «mia madre, 78, disabile»,
#: non solo «sono/è disabile».
_DISABILITA_RE = re.compile(
    r"\b(?:disabil(?:e|i|ità|ita)|invalid(?:o|a|i|ità|ita)|handicap)\b",
    re.IGNORECASE,
)


def _disabilita_dichiarata_nel_testo(messaggio: str) -> bool:
    """Se QUESTO messaggio nomina la disabilita' della persona di cui si
    parla. Recupero deterministico, come eta'/ISEE: la conferma il testo, non
    il modello (R-8). Se pero' la disabilita' e' del figlio e' un'altra cosa
    (`disabilita_nucleo`), gestita da `_figlio_disabile_dichiarato_nel_testo`:
    qui si cede il passo per non confondere le due."""
    if not messaggio:
        return False
    if _figlio_disabile_dichiarato_nel_testo(messaggio):
        return False
    return bool(_DISABILITA_RE.search(messaggio))


def _e_bando_di_trasporto_pubblico(messaggio: str) -> bool:
    """«bandi per i mezzi pubblici», «bandi trasporto pubblico»: il messaggio
    nomina "bandi" ma l'argomento vero e' l'abbonamento/agevolazione sul
    trasporto pubblico locale, non un elenco generico di avvisi pubblici.

    Stessa idea delle trappole gia' presidiate su comune («bolletta»,
    «minori») e su topic generico (`_BONUS_GENERICO_RE`): una parola-chiave
    da sola non basta quando un'altra, piu' specifica, compare nella stessa
    frase. Senza questa guardia «bandi per i mezzi pubblici» risolveva
    BANDI solo perche' "bandi" e' la prima parola-chiave incontrata, e
    TRASPORTO_PUBBLICO (introdotta proprio per questa frase, vedi il
    commento sul suo valore nell'enum) non veniva mai raggiunto."""
    haystack = messaggio.casefold()
    ha_bandi = any(k in haystack for k in TOPIC_KEYWORDS[Topic.BANDI])
    ha_trasporto = any(k in haystack for k in TOPIC_KEYWORDS[Topic.TRASPORTO_PUBBLICO])
    return ha_bandi and ha_trasporto


def _confirm_beneficiary_role(
    *, message: str, role: BeneficiaryRole | None
) -> BeneficiaryRole | None:
    """Discard a model-claimed role the citizen's own text does not actually
    state (see `BENEFICIARY_ROLE_MARKERS`). Never upgrades `None` into a
    role — only ever downgrades an unconfirmed claim back to `None`."""
    if role is None:
        return None
    markers = BENEFICIARY_ROLE_MARKERS.get(role, ())
    haystack = message.casefold()
    return role if any(marker in haystack for marker in markers) else None


def _confirm_comune_hint(*, message: str, hint: str | None) -> str | None:
    """Scarta un comune che il cittadino non ha nominato.

    Asked "orari ufficio anagrafe Camposampiero", the model returned
    `comune_hint="Albano Laziale"` — the comune named in its own system
    prompt, not in the citizen's sentence. The answer that followed was
    Albano's office, its phone number and its opening hours, presented to
    someone asking about a comune 500 km away. Nothing downstream could catch
    it: every later step treats `comune_hint` as something the citizen said.

    So it is checked here, the same way `_confirm_beneficiary_role` checks the
    role (R-9): the hint survives only if its own words appear in the
    citizen's text. Never invents a hint, only ever discards one that is not
    evidenced — comparison is accent- and case-insensitive because "Forlì" and
    "Forli" are the same comune typed by two different people.
    """
    if hint is None or not hint.strip():
        return None

    def piatto(testo: str) -> str:
        senza_accenti = "".join(
            c
            for c in unicodedata.normalize("NFKD", testo.casefold())
            if not unicodedata.combining(c)
        )
        return re.sub(r"[^\w\s]", " ", senza_accenti)

    parole_messaggio = set(piatto(message).split())
    parole_hint = [p for p in piatto(hint).split() if len(p) > 2]
    if not parole_hint:
        return None
    # Ogni parola del nome deve comparire: "Reggio" da solo non conferma
    # "Reggio Emilia", e mezzo nome è esattamente il modo in cui si finisce
    # nel comune sbagliato.
    return hint if all(p in parole_messaggio for p in parole_hint) else None


class ProfileSlots(BaseModel):
    """Anagraphic/economic facts the citizen volunteered in free text.

    Every field is optional and stays `None` unless the citizen stated it
    explicitly — the model is instructed not to infer or round. This mirrors
    `Requirements`' own semantics in `schema.py`: absence is data, not zero.
    """

    eta: int | None = Field(default=None, ge=0, le=130)
    #: `float`, not `Decimal` — `Decimal`'s pydantic-generated JSON Schema
    #: carries a lookahead regex `pattern` that llama.cpp/Ollama's
    #: grammar-constrained decoding cannot parse (measured: `qwen3:4b`
    #: returns HTTP 400 "failed to parse grammar" with a `Decimal` field
    #: anywhere in the schema). Converted to `Decimal` before it ever
    #: reaches `CitizenProfile` in `treasureiq.chat.respond`.
    isee: float | None = Field(default=None, ge=0)
    nucleo_familiare: int | None = Field(default=None, ge=1)
    figli_minori: int | None = Field(default=None, ge=0)
    disabilita: bool | None = None
    #: Sesso dichiarato ESPLICITAMENTE dal cittadino ("sono una donna/un
    #: uomo"), non la deduzione dal nome proprio (D-52) — quella e'
    #: deterministica, gira fuori dal grammar del modello, e vive in
    #: `chat.nomi_genere.sesso_da_nome`, chiamata da
    #: `treasureiq.chat.respond._profile_from_slots`. `Literal["f", "m"]`,
    #: non un enum piu' ampio: e' l'unico asse su cui i dati del seed
    #: (contrassegno rosa) discriminano davvero (R-DATA).
    sesso: Literal["f", "m"] | None = None
    #: Almeno un figlio con disabilita' nel nucleo — non riferito al
    #: cittadino stesso (quello resta `disabilita`). Un conteggio, non un
    #: modello per-membro (D-53, DEFERRED vieta la seconda strada).
    figli_disabili: int | None = Field(default=None, ge=0)
    #: Normalmente ricavato da `figli_disabili` in
    #: `treasureiq.chat.respond._profile_from_slots`
    #: (`figli_disabili > 0 → True`); resta un campo separato perche' il
    #: cittadino puo' dichiararlo senza dire un numero ("ho un figlio
    #: disabile" senza "quanti").
    disabilita_nucleo: bool | None = None
    employment_status: EmploymentStatus | None = None


class ChatIntent(BaseModel):
    """The model's entire contribution to understanding the citizen's turn."""

    topic: Topic
    kind: QuestionKind = QuestionKind.AGEVOLAZIONE
    comune_hint: str | None = Field(
        default=None,
        max_length=100,
        description="Comune name as the citizen wrote it, if any. Used only "
        "as a lookup key against known comuni — never rendered back verbatim.",
    )
    slots: ProfileSlots = Field(default_factory=ProfileSlots)
    beneficiary_role: BeneficiaryRole | None = Field(
        default=None,
        description="Chi riceve il servizio, SOLO per i topic dove questo "
        "cambia cosa cercare (vedi AMBIGUOUS_ROLE_TOPICS). Mai dedotto dal "
        "solo argomento della domanda.",
    )


class ChatRecognitionContract(BaseModel):
    """Contratto v1 dell'interpretazione di un turno cittadino.

    `ChatIntent` resta la forma compatibile della classificazione; questo
    involucro aggiunge le evidenze deterministiche che servono al planner.
    Nessun campo decide la fonte o scrive la risposta: il contratto descrive
    soltanto ciò che il cittadino ha detto e il contesto che può essere
    riutilizzato.
    """

    version: Literal["v1"] = "v1"
    message: str = Field(min_length=1)
    intent: ChatIntent
    filter_keys: tuple[str, ...] = ()
    context_turns: int = Field(default=0, ge=0)
    municipality_explicit: bool = False


def build_recognition_contract(
    *, message: str, intent: ChatIntent, storia: list[str] | None = None
) -> ChatRecognitionContract:
    """Envelope deterministico attorno all'intent già guard-railato.

    I filtri sono letti dalla sola funzione canonica `riconosci_filtri`; il
    modello non può aggiungerne. La funzione è intenzionalmente piccola: il
    routing delle fonti appartiene al QueryPlan, non a questo contratto.
    """

    from treasureiq.chat.filtri import riconosci_filtri

    filtri = riconosci_filtri(message)
    return ChatRecognitionContract(
        message=message,
        intent=intent,
        filter_keys=tuple(dict.fromkeys(f.chiave.value for f in filtri)),
        context_turns=len(storia or []),
        municipality_explicit=bool(intent.comune_hint),
    )


class _ModelIntent(BaseModel):
    """Minimal shape asked of the LLM (D-01, ciclo11): topic/kind/comune_hint/
    beneficiary_role only — no `slots`. Asking the model for anagraphic slots
    was redundant with `treasureiq.chat.filtri.riconosci_filtri` (B2) and, on
    isee especially, less accurate: the model echoed the same truncated
    figures the old regex had, `riconosci_filtri` doesn't. Slots now come
    from that single deterministic source in `respond.py`/`api.py`, never
    from Ollama (closes D-05's double-wiring)."""

    topic: Topic
    kind: QuestionKind = QuestionKind.AGEVOLAZIONE
    comune_hint: str | None = Field(
        default=None,
        max_length=100,
        description="Comune name as the citizen wrote it, if any. Used only "
        "as a lookup key against known comuni — never rendered back verbatim.",
    )
    beneficiary_role: BeneficiaryRole | None = Field(
        default=None,
        description="Chi riceve il servizio, SOLO per i topic dove questo "
        "cambia cosa cercare (vedi AMBIGUOUS_ROLE_TOPICS). Mai dedotto dal "
        "solo argomento della domanda.",
    )


def _topic_hint_lines() -> str:
    """One line per topic, `value: esempio, esempio` — a cheat-sheet for the

    system prompt. Built from `TOPIC_KEYWORDS` rather than duplicated by
    hand, so the two can never drift apart. Small local models classify far
    more reliably against a few example phrases per category than against a
    bare enum of slugs.
    """
    lines = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if topic is Topic.SCONOSCIUTO:
            continue
        # Il trattino finale è notazione per il matcher (radice tronca, vedi
        # `_keyword_hit`): al modello va mostrata la parola, non la notazione.
        esempi = ", ".join(k.rstrip("-") for k in keywords)
        lines.append(f'- "{topic.value}": {esempi}')
    return "\n".join(lines)


INTENT_SYSTEM_PROMPT = f"""Sei un classificatore per una chat civica comunale \
italiana. Ricevi il messaggio libero di un cittadino e produci ESCLUSIVAMENTE \
un oggetto strutturato, mai testo libero, mai una risposta al cittadino.

Non conosci in anticipo di quale Comune parli il cittadino: NON assumerne mai uno. \
Compila `comune_hint` solo se il cittadino scrive esplicitamente il nome del comune \
nel proprio messaggio; altrimenti lascialo vuoto.

Compila questi campi:
- kind: la FORMA della domanda, da decidere PRIMA del topic.
  "agevolazione": il cittadino chiede se ha diritto a qualcosa — un contributo, uno \
sconto, un aiuto economico — e si aspetta un verdetto. Esempi: "ho la bolletta troppo \
alta", "ho diritto a...", "ci sono agevolazioni per...", "posso avere un contributo per...".
  "informazione": il cittadino vuole un fatto civico — un orario, un calendario, un \
servizio, un ufficio — senza chiedere un verdetto di idoneità. Esempi: "quando ritirano \
il vetro", "cerco un servizio di volontariato per anziani", "dove si trova l'ufficio...".
  Nel dubbio, se il messaggio nomina una data, un calendario, un orario o un servizio da \
trovare, è "informazione"; se nomina un diritto, un contributo o una difficoltà economica, \
è "agevolazione".
- topic: l'argomento del messaggio, scelto tra le categorie chiuse elencate sotto, \
ciascuna con qualche esempio delle parole che un cittadino potrebbe usare:
{_topic_hint_lines()}
  Se il messaggio parla di una bolletta, di un costo di un'utenza domestica o di una \
difficoltà a pagarla, il topic corretto è "sostegno_utenze" anche se il Comune non \
pubblica nulla su questo — è comunque un argomento riconosciuto, semplicemente senza \
dati. Usa "sconosciuto" solo quando il messaggio non parla di nessuno di questi temi \
(es. domande generiche, saluti, argomenti non civici). Non scegliere una categoria \
plausibile solo per evitare "sconosciuto": è una risposta corretta quando è quella vera.
- comune_hint: il nome del comune SOLO se il cittadino lo scrive esplicitamente.
- slots: dati anagrafici o economici (età, ISEE, numero di persone nel nucleo, figli \
minori, disabilità, condizione lavorativa) SOLO se il cittadino li dichiara \
esplicitamente nel messaggio. Non dedurre, non stimare, non arrotondare: in caso di \
dubbio lascia il campo vuoto.
- sesso: SOLO se il cittadino lo dichiara esplicitamente ("sono una donna", "sono un \
uomo"). Non dedurlo mai da un nome proprio, da un pronome o da come si firma: quella \
deduzione la fa un altro sistema, deterministico, fuori da questa classificazione.
- figli_disabili / disabilita_nucleo: SOLO se il cittadino dichiara che un figlio (non \
se stesso) ha una disabilità. "figlio disabile", "mio figlio è disabile", "ho una figlia \
con disabilità" → disabilita_nucleo vero; se dice quanti, anche figli_disabili. Non \
confondere con "disabilita" (quella è riferita al cittadino stesso).
- beneficiary_role: SOLO per argomenti come "volontariato", dove chi riceve il servizio \
e chi lo offre sono due persone diverse. Il verbo usato conta più delle parole "anziani" \
o "volontariato", che da sole non dicono nulla sul ruolo:
  - "cercare/trovare/c'è un servizio di..." (il cittadino CERCA qualcosa da ricevere) → \
lascia beneficiary_role VUOTO, a meno che il messaggio non dica anche esplicitamente \
"per me" (allora "assistito").
  - "voglio fare volontariato / offrirmi come volontario / dare una mano / aiutare io" \
(il cittadino OFFRE il proprio aiuto) → "volontario".
  - "per me" / "sono io che ne ho bisogno" (il cittadino chiede per sé) → "assistito".
  Esempio: "cerco un servizio di volontariato per anziani" NON è una dichiarazione di \
ruolo — è una RICERCA, non dice se il cittadino è l'anziano che cerca aiuto o la persona \
che vuole aiutare gli anziani. In questo caso beneficiary_role resta VUOTO. Nel dubbio, \
lascia sempre vuoto: non indovinare mai.

Non decidi se il cittadino ha diritto a qualcosa: quello lo fa un altro sistema."""


#: Quale motore classifica topic/kind.
#:   "model" (default): il modello LLM via `provider.aparse`, comportamento
#:     storico invariato.
#:   "scorer": lo scorer deterministico livello A in Python
#:     (`intent_scorer.score_intent`) — niente modello, esito riproducibile.
#:   "rust": lo stesso scorer, ma il crate nativo PyO3 `tiq_intent` (parità
#:     35/35 sull'oracolo, ~6-7x piu' veloce dello scorer Python). Se il modulo
#:     nativo non e' installato (immagine senza wheel) ripiega su "scorer".
#: I rami deterministici ("scorer"/"rust") condividono la stessa cintura a
#: valle (_confirm_*, R-8): cambia solo CHI propone topic/kind, non le guardie.
_INTENT_BACKEND = os.environ.get("TREASUREIQ_INTENT_BACKEND", "model").strip().lower()

#: Backend che NON chiamano il modello: lo scorer deterministico livello A.
_BACKEND_DETERMINISTICI = frozenset({"scorer", "rust"})


def _beneficiary_role_da_testo(message: str) -> BeneficiaryRole | None:
    """Deriva il ruolo dai SOLI marcatori nel testo — esattamente l'esito che
    `_confirm_beneficiary_role` (R-9) terrebbe comunque.

    Il ruolo finale non e' mai stato una scelta del modello: qualunque cosa
    proponesse, sopravviveva solo se un marcatore era presente nel testo del
    cittadino. Col backend scorer il modello non c'e' piu' a proporlo, quindi
    lo si ricava direttamente dai marcatori. Nessun ruolo se il testo non lo
    dichiara; nessun ruolo nemmeno se ne dichiara due insieme (ambiguo ->
    None, non si indovina)."""
    haystack = message.casefold()
    trovati = [
        role
        for role, markers in BENEFICIARY_ROLE_MARKERS.items()
        if any(marker in haystack for marker in markers)
    ]
    return trovati[0] if len(trovati) == 1 else None


def _score_livello_a(message: str) -> tuple[str, str]:
    """(topic, kind) dallo scorer deterministico. Backend "rust" usa il crate
    nativo `tiq_intent` (parità 35/35, ~6-7x); se il modulo non c'e' ripiega
    sullo scorer Python — stesso output, solo piu' lento (fail-safe, mai
    crash su un'immagine senza wheel)."""
    if _INTENT_BACKEND == "rust":
        try:
            import tiq_intent

            topic, kind, _conf = tiq_intent.score(message)
            return topic, kind
        except ImportError:
            pass  # nessun wheel nativo: giu' allo scorer Python
    esito = score_intent(message)
    return esito.topic, esito.kind


def _intent_dallo_scorer(message: str) -> "_ModelIntent":
    """Costruisce un `_ModelIntent` dallo scorer deterministico, nella stessa
    forma che il modello avrebbe restituito, cosi' la cintura a valle non
    distingue i due backend. `comune_hint` resta None (lo scorer non tocca il
    comune: lo risolve `_comuni_candidati`/`risolvi_comune` dal testo, e
    `_confirm_comune_hint` lo azzererebbe comunque)."""
    topic, kind = _score_livello_a(message)
    return _ModelIntent(
        topic=Topic(topic),
        kind=QuestionKind(kind),
        comune_hint=None,
        beneficiary_role=_beneficiary_role_da_testo(message),
    )


async def extract_intent(
    *,
    message: str,
    provider: LLMProvider,
    storia: list[str] | None = None,
    backend: str | None = None,
) -> ChatIntent:
    """Classify one citizen message. Never raises — falls back to `SCONOSCIUTO`.

    A model outage must not take the whole `/api/chat` endpoint down with it
    (see the module docstring in `treasureiq.chat.respond`); losing the
    ability to classify intent still leaves a safe, honest answer available.

    `storia` (D-47), when given, is the citizen's own last few turns — passed
    to the model as LABELED context only, so a short follow-up like «e per lo
    scuolabus?» can be read against what was asked before it. The
    classification TARGET stays `message`, never the history: `comune_hint`
    and `beneficiary_role` are still confirmed against `message` alone below
    (R-9). `ChatIntent.slots` always comes back empty here — D-01 (ciclo11):
    the model is only asked for `topic`/`kind`/`comune_hint`/`beneficiary_role`
    now (see `_ModelIntent`), never anagraphic slots, so there is nothing left
    to leak from `storia` into an unrelated turn. Slots are read from
    `message` alone, downstream, by `treasureiq.chat.filtri.riconosci_filtri`
    (the single source of truth, closing D-05's double-wiring). Deterministic
    *carryover* of a whole topic or comune across turns is not this
    function's job: see `treasureiq.chat.respond._eredita_dal_contesto`,
    which never trusts the model alone for that (D-47 hard rule).
    """
    # The engine can select its rail per request without mutating the module
    # setting (and without a race between concurrent requests).
    effective_backend = (backend or _INTENT_BACKEND).strip().lower()
    try:
        if effective_backend in _BACKEND_DETERMINISTICI:
            # Livello A deterministico: nessuna chiamata al modello, nessun
            # bisogno di `storia` (il carryover di topic/comune fra turni non
            # e' compito di questa funzione — lo fa `respond._eredita_dal_contesto`).
            parsed = _intent_dallo_scorer(message)
        else:
            user_message = message
            if storia:
                turni_precedenti = "\n".join(f"- {turno}" for turno in storia[-3:])
                user_message = (
                    "Turni precedenti del cittadino (solo per capire il contesto, "
                    "NON classificare questi):\n"
                    f"{turni_precedenti}\n\n"
                    f"Messaggio da classificare: {message}"
                )
            parsed = await provider.aparse(
                system=INTENT_SYSTEM_PROMPT, user=user_message, output_model=_ModelIntent
            )
        confirmed_role = _confirm_beneficiary_role(message=message, role=parsed.beneficiary_role)
        updates: dict[str, object] = {}
        if confirmed_role != parsed.beneficiary_role:
            updates["beneficiary_role"] = confirmed_role
        confirmed_hint = _confirm_comune_hint(message=message, hint=parsed.comune_hint)
        if confirmed_hint != parsed.comune_hint:
            updates["comune_hint"] = confirmed_hint
        if (
            parsed.topic in INFORMATIONAL_BY_NATURE_TOPICS
            and parsed.kind is not QuestionKind.INFORMAZIONE
        ):
            # R-8: the model reads a verb like "voglio fare volontariato" as
            # a benefit request, but these topics have no eligibility
            # criteria for `match/engine.py` to evaluate at all — `kind` is
            # not the model's call to make here, so it is overridden
            # deterministically rather than left to prompting (which did not
            # hold for `beneficiary_role` either).
            updates["kind"] = QuestionKind.INFORMAZIONE
        if (
            effective_backend not in _BACKEND_DETERMINISTICI
            and updates.get("kind", parsed.kind) is QuestionKind.AGEVOLAZIONE
            and parsed.topic is not Topic.SCONOSCIUTO
            and _BONUS_GENERICO_RE.search(message)
            and not _topic_keyword_presente(message)
        ):
            # R-8: «ho bonus?» senza nominare una categoria e' una domanda
            # generica, ma qwen3:4b la incolla comunque a un topic specifico
            # (nel caso reale: sostegno_utenze). Cosi' la scheda mostrava un
            # interesse mai dichiarato e la domanda-categoria (D-55) non partiva
            # mai. Senza un aggancio nel testo il topic torna a SCONOSCIUTO —
            # il segnale con cui `respond` chiede quale categoria.
            # Esente il backend scorer: li' un topic != SCONOSCIUTO E' gia'
            # la prova che una keyword ha matchato (lo scorer non incolla mai
            # un topic senza hit), quindi questa toppa e' redundante e
            # declasserebbe a torto casi legittimi tipo «bonus per il gas».
            updates["topic"] = Topic.SCONOSCIUTO
        if (
            updates.get("topic", parsed.topic) is Topic.BANDI
            and _e_bando_di_trasporto_pubblico(message)
        ):
            # Guardia bandi/trasporto: «bandi per i mezzi pubblici» non e'
            # una richiesta di elenco avvisi, e' TRASPORTO_PUBBLICO che
            # nomina anche "bandi" (vedi `_e_bando_di_trasporto_pubblico`).
            updates["topic"] = Topic.TRASPORTO_PUBBLICO
        if updates:
            parsed = parsed.model_copy(update=updates)
        return ChatIntent(
            topic=parsed.topic,
            kind=parsed.kind,
            comune_hint=parsed.comune_hint,
            beneficiary_role=parsed.beneficiary_role,
            slots=ProfileSlots(),
        )
    except Exception:
        logger.warning("intent extraction failed, falling back to sconosciuto", exc_info=True)
        return ChatIntent(topic=Topic.SCONOSCIUTO)


#: «ho 38 anni», «38enne», «ho compiuto 38 anni». L'età sta sempre accanto
#: alla parola, e leggerla con un'espressione regolare costa niente.
_ETA_NEL_TESTO = re.compile(
    r"\b(?:ho\s+|di\s+|età\s+|eta\s+)?(?P<eta>\d{1,3})\s*(?:anni|enne\b)", re.I
)

#: «ISEE 12.000», «isee di 12000 euro», «isee 9.360,50».
_ISEE_NEL_TESTO = re.compile(
    r"\bisee\b[^\d]{0,20}(?P<isee>\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d{3,6}(?:,\d{1,2})?)",
    re.I,
)

#: «famiglia di 4», «nucleo di 4», «siamo in 4»: il numero di persone nel
#: nucleo, letto dal testo con lo stesso principio di eta'/ISEE — mai dal
#: modello. Il gap che ha aggiunto questo pattern: la chat anonima (senza
#: cookie CIE/SPID) non aveva NESSUN ripiego dal testo per questo campo, a
#: differenza di eta'/isee/sesso/disabilita_nucleo, quindi l'eco combinata
#: (D-52/D-53, acc1) restava senza il nucleo anche quando il cittadino lo
#: aveva scritto per esteso.
_NUCLEO_NEL_TESTO = re.compile(
    r"\b(?:famiglia|nucleo)\s+di\s+(?P<nucleo>\d{1,2})\b"
    r"|\bsiamo\s+in\s+(?P<nucleo2>\d{1,2})\b",
    re.I,
)

#: Numeri scritti a parole che un cittadino usa per i figli.
_PAROLE_NUMERO = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5}

#: «2 figli minorenni», «due figli minori», «un figlio minore», «figli
#: piccoli»: quanti minori nel nucleo, letto dal testo come eta'/ISEE/nucleo —
#: mai dal modello, che questo slot lo riempie in modo inaffidabile. Il
#: qualificatore «minor…»/«minorenn…»/«piccol…» e' OBBLIGATORIO: «ho due figli»
#: adulti non deve contare come figli minori. Conteggio assente → 1.
_FIGLI_MINORI_NEL_TESTO = re.compile(
    r"\b(?P<n>\d{1,2}|un|uno|una|due|tre|quattro|cinque)?\s*"
    r"figl[io]\w*\s+(?:minorenn\w+|minor\w+|piccol\w+)",
    re.I,
)


def slot_dal_testo(messaggio: str) -> dict:
    """Età e ISEE letti dal testo, senza passare dal modello.

    Il modello questi due li sbaglia in due modi diversi e ugualmente cari: a
    volte non li vede — «ho 38 anni» restava fuori dal profilo, e la scheda
    continuava a chiedere l'età al cittadino che l'aveva appena scritta — e a
    volte li riscrive, che su una cifra è peggio di non vederla.

    È la stessa regola che vale per le soglie nei verdetti: le cifre non le
    produce il modello. Qui si applica anche in ingresso.
    """
    trovati: dict = {}
    if not messaggio:
        return trovati

    eta = _ETA_NEL_TESTO.search(messaggio)
    if eta:
        valore = int(eta.group("eta"))
        # Oltre i 130 non è un'età: è un importo o un numero civico finito
        # accanto alla parola sbagliata.
        if 0 < valore <= 130:
            trovati["eta"] = valore

    isee = _ISEE_NEL_TESTO.search(messaggio)
    if isee:
        grezzo = isee.group("isee").replace(".", "").replace(" ", "").replace(",", ".")
        try:
            trovati["isee"] = float(grezzo)
        except ValueError:
            pass

    nucleo = _NUCLEO_NEL_TESTO.search(messaggio)
    if nucleo:
        grezzo_nucleo = nucleo.group("nucleo") or nucleo.group("nucleo2")
        valore_nucleo = int(grezzo_nucleo)
        if valore_nucleo >= 1:
            trovati["nucleo_familiare"] = valore_nucleo

    figli = _FIGLI_MINORI_NEL_TESTO.search(messaggio)
    if figli:
        grezzo_figli = figli.group("n")
        if grezzo_figli is None:
            valore_figli = 1  # «ho figli minori», senza numero → almeno uno
        elif grezzo_figli.isdigit():
            valore_figli = int(grezzo_figli)
        else:
            valore_figli = _PAROLE_NUMERO.get(grezzo_figli.lower(), 1)
        if valore_figli >= 1:
            trovati["figli_minori"] = valore_figli

    return trovati


#: Una domanda su un beneficio detta in astratto — «ho bonus?», «c'e' qualche
#: agevolazione a cui posso accedere?». Non nomina una categoria: da sola non
#: dice a quale topic appartiene. «aiuto» resta fuori di proposito (e' anche un
#: verbo di richiesta generica, non solo un beneficio).
_BONUS_GENERICO_RE = re.compile(
    r"\b(?:bonus|agevolazion\w*|incentiv\w*|sussid\w*|contribut\w*)\b",
    re.IGNORECASE,
)


def _topic_keyword_presente(messaggio: str) -> bool:
    """Se il testo contiene un aggancio a un topic specifico (le stesse
    parole-stem di `TOPIC_KEYWORDS`). Serve a distinguere «bonus bollette»
    (ancorato) da «ho bonus?» (generico)."""
    if not messaggio:
        return False
    haystack = messaggio.casefold()
    for keywords in TOPIC_KEYWORDS.values():
        for parola in keywords:
            if parola.rstrip("-").casefold() in haystack:
                return True
    return False
