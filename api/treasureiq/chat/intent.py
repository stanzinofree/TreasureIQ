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
    #: The model could not map the message onto any of the above. Never
    #: guessed into just to avoid this value — see the system prompt.
    SCONOSCIUTO = "sconosciuto"


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
    Topic.SCONOSCIUTO: (),
}


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
    comune_hint: str | None = Field(
        default=None,
        max_length=100,
        description="Comune name as the citizen wrote it, if any. Used only "
        "as a lookup key against known comuni — never rendered back verbatim.",
    )
    slots: ProfileSlots = Field(default_factory=ProfileSlots)


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

Non decidi se il cittadino ha diritto a qualcosa: quello lo fa un altro sistema."""


async def extract_intent(*, message: str, provider: LLMProvider) -> ChatIntent:
    """Classify one citizen message. Never raises — falls back to `SCONOSCIUTO`.

    A model outage must not take the whole `/api/chat` endpoint down with it
    (see the module docstring in `treasureiq.chat.respond`); losing the
    ability to classify intent still leaves a safe, honest answer available.
    """
    try:
        return await provider.aparse(
            system=INTENT_SYSTEM_PROMPT, user=message, output_model=ChatIntent
        )
    except Exception:
        logger.warning("intent extraction failed, falling back to sconosciuto", exc_info=True)
        return ChatIntent(topic=Topic.SCONOSCIUTO)
