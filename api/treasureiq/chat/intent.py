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
from enum import Enum

from pydantic import BaseModel, Field

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
    Topic.MENSA_SCOLASTICA: ("mensa",),
    Topic.CONTRIBUTO_LIBRI: ("libri di testo", "sussidi didattici", "libri scolastici"),
    Topic.BORSA_STUDIO: ("borsa di studio", "iostudio"),
    Topic.VOUCHER_CONCILIAZIONE: (
        "voucher",
        "conciliazione vita-lavoro",
        "asilo nido",
        "centro estivo",
    ),
    Topic.ASSEGNO_MATERNITA: ("maternit", "gravidanza", "permesso rosa"),
    Topic.CONTRIBUTO_AFFITTO: ("affitto", "locazione", "canone di locazione", "sfratto"),
    Topic.SOSTEGNO_UTENZE: (
        "bolletta",
        "bollette",
        "utenze",
        "energia elettrica",
        "gas",
        "utenza elettrica",
    ),
    Topic.ASSISTENZA_DISABILITA: ("disabilit", "alzheimer", "assistenza domiciliare"),
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
        lines.append(f'- "{topic.value}": {", ".join(keywords)}')
    return "\n".join(lines)


INTENT_SYSTEM_PROMPT = f"""Sei un classificatore per la chat civica del Comune di \
Albano Laziale. Ricevi il messaggio libero di un cittadino e produci ESCLUSIVAMENTE \
un oggetto strutturato, mai testo libero, mai una risposta al cittadino.

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


async def extract_intent(*, message: str, provider: LLMProvider) -> ChatIntent:
    """Classify one citizen message. Never raises — falls back to `SCONOSCIUTO`.

    A model outage must not take the whole `/api/chat` endpoint down with it
    (see the module docstring in `treasureiq.chat.respond`); losing the
    ability to classify intent still leaves a safe, honest answer available.
    """
    try:
        parsed = await provider.aparse(
            system=INTENT_SYSTEM_PROMPT, user=message, output_model=ChatIntent
        )
        confirmed_role = _confirm_beneficiary_role(message=message, role=parsed.beneficiary_role)
        updates: dict[str, object] = {}
        if confirmed_role != parsed.beneficiary_role:
            updates["beneficiary_role"] = confirmed_role
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
        if updates:
            parsed = parsed.model_copy(update=updates)
        return parsed
    except Exception:
        logger.warning("intent extraction failed, falling back to sconosciuto", exc_info=True)
        return ChatIntent(topic=Topic.SCONOSCIUTO)
