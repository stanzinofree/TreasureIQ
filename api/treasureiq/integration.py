"""Per-ente integration cost and access-mode ladder (D-21, D-24, D-26).

Every ente TreasureIQ names gets a machine-readable, dated record of what it
would cost to integrate its services — and the label for that cost is a
lookup on *how the data is exposed*, never a numeric threshold picked by
hand (D-21). A threshold is an opinion about a comune; the access mode is a
fact about a portal.

The composition functions here (`diagnosis_lines`, `cost_lines`) exist
because D-24 forbids handing cost judgements to a model: the strings are
built purely from typed fields, so the same probe always produces the same
sentence. D-26 sets three hard rules for that sentence, enforced in the
templates below rather than left to whoever edits them next:

1. every fact carries the date and method it was measured with — an undated
   cost is an opinion, not a measurement;
2. the cost is TreasureIQ's, never the citizen's — no line here may imply a
   citizen pays for a portal's missing API;
3. copy may describe what a portal exposes, never judge the people who run
   it — "il portale non espone X" is allowed, "il Comune non lavora" is not.
"""

from __future__ import annotations

import json
import os
from datetime import date
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from treasureiq.ingest.websearch import WebSearchCacheEntry, load_cached

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("TREASUREIQ_DATA_DIR", REPO_ROOT / "data"))
ENTI_PATH = DATA_DIR / "enti.json"
WEBSEARCH_CACHE_DIR = DATA_DIR / "websearch-cache"


class AccessMode(str, Enum):
    """The access-mode ladder (D-21). Six rungs, each a fact about the
    channel a portal offers — not an opinion about how hard it feels."""

    M1_CAMPO_TIPIZZATO = "M1_campo_tipizzato"
    M2_PROSA_API = "M2_prosa_api"
    M3_ALLEGATO = "M3_allegato"
    M4_CONNETTORE = "M4_connettore"
    M5_NESSUNO = "M5_nessuno"
    M6_WEB_APERTO = "M6_web_aperto"


#: Label derives from the mode by dict lookup only — never a threshold
#: (D-21). Adding a rung means adding one entry here, nothing else.
MODE_LABELS: dict[AccessMode, str] = {
    AccessMode.M1_CAMPO_TIPIZZATO: "basso",
    AccessMode.M2_PROSA_API: "medio",
    AccessMode.M3_ALLEGATO: "medio-alto",
    AccessMode.M4_CONNETTORE: "alto",
    AccessMode.M5_NESSUNO: "non recuperabile",
    AccessMode.M6_WEB_APERTO: "massimo, provenienza non verificata",
}

#: What each mode costs TreasureIQ to integrate, in one deterministic
#: sentence. `{label}` is filled from MODE_LABELS — the label always agrees
#: with the mode because both come from the same enum key (D-21).
_COST_TEMPLATES: dict[AccessMode, str] = {
    AccessMode.M1_CAMPO_TIPIZZATO: (
        "Integrazione a costo {label}: il dato arriva già in un campo "
        "tipizzato di un'API pubblica, pronto per un parser."
    ),
    AccessMode.M2_PROSA_API: (
        "Integrazione a costo {label}: il dato è raggiungibile via API ma "
        "va estratto da un campo testuale — serve lettura assistita, non "
        "solo un parser."
    ),
    AccessMode.M3_ALLEGATO: (
        "Integrazione a costo {label}: il dato è dentro un allegato, non "
        "in un campo — serve un passaggio di estrazione documentale prima "
        "di poter essere letto."
    ),
    AccessMode.M4_CONNETTORE: (
        "Integrazione a costo {label}: il portale non espone un'API — "
        "serve un connettore dedicato a questa pagina HTML, da mantenere "
        "ogni volta che il portale cambia struttura."
    ),
    AccessMode.M5_NESSUNO: (
        "Integrazione a costo {label}: nessun canale, istituzionale o "
        "web, restituisce oggi questo dato."
    ),
    AccessMode.M6_WEB_APERTO: (
        "Integrazione a costo {label}: il dato compare solo sul web "
        "aperto, fuori da qualunque fonte istituzionale — la provenienza "
        "non è verificata e va trattata come tale."
    ),
}


class Probe(BaseModel):
    """One measurement: what was run, when, and what it found.

    `dettagli` holds the measured facts verbatim, keyed by what was
    checked — deliberately a dict rather than fixed fields, because each
    portal fails or succeeds in a different way and forcing one shape onto
    all of them would mean padding empty fields with guesses (D-16: fields
    not measured stay absent, never zero).
    """

    method: str
    dated: date
    dettagli: dict[str, str] = Field(default_factory=dict)


class UrpContact(BaseModel):
    """The office a citizen (or TreasureIQ) can actually call.

    `fonte` and `verificato_il` exist for the same reason `Probe` carries
    `method`/`dated`: a contact without a source and a verification date is
    not usable evidence, it is a guess with a phone number attached.
    """

    nome: str
    fonte: str
    verificato_il: date
    telefono: str | None = None
    email: str | None = None
    orari: str | None = None


class IpaRecord(BaseModel):
    """The body's entry in the Indice della Pubblica Amministrazione.

    IPA is the official registry every Italian public body is required to keep
    current, published as open data with an API meant for programmatic use.
    That makes it a better source for "who do I write to" than a web search
    could ever be: no ranking to second-guess, no lookalike domain to mistake
    for the real one, and no rate limit standing between us and the answer.

    What it does *not* carry is opening hours — IPA records the institutional
    channel, not the counter timetable. Those stay in `UrpContact`, read from
    the comune's own page and dated there. Two sources, each cited for what it
    actually knows.
    """

    codice_ipa: str
    denominazione: str
    #: The address for legally valid correspondence. This is the channel that
    #: obliges an answer, which is why it is worth showing a citizen at all.
    pec: str | None = None
    indirizzo: str | None = None
    sito: str | None = None
    fonte: str
    verificato_il: date


class Ente(BaseModel):
    """One public body's integration record: cost, mode, contact — dated."""

    ente: str
    codice_istat: str
    access_mode: AccessMode
    probe: Probe
    dati_gov_probe: Probe | None = None
    datasets_on_dati_gov: int | None = None
    calendario_raccolta_open_data_comuni: int | None = None
    urp: UrpContact | None = None
    ipa: IpaRecord | None = None


@lru_cache(maxsize=1)
def load_enti() -> dict[str, Ente]:
    """Load every ente record, keyed by ISTAT code. Cached: the source file
    is static data shipped with the repo, not something that changes at
    runtime."""
    raw = json.loads(ENTI_PATH.read_text("utf-8"))
    return {item["codice_istat"]: Ente.model_validate(item) for item in raw}


def load_websearch(query: str) -> WebSearchCacheEntry | None:
    """Read-only lookup into B18's cache. Never touches the network — the
    fetch happens at ingestion time, not here."""
    return load_cached(query, WEBSEARCH_CACHE_DIR)


def diagnosis_lines(ente: Ente) -> list[str]:
    """What was measured, as facts about the portal (D-26 rule 3): never a
    judgement about the people who run it."""
    lines = [
        (
            f"{ente.ente}: accesso {MODE_LABELS[ente.access_mode]} "
            f"({ente.access_mode.value})."
        )
    ]
    lines.append(f"Misurato il {ente.probe.dated.isoformat()} — {ente.probe.method}.")
    for chiave, valore in ente.probe.dettagli.items():
        lines.append(f"{chiave}: {valore}.")
    return lines


def cost_lines(ente: Ente) -> list[str]:
    """The cost sentence plus its supporting evidence — deterministic,
    composed only from fields (D-24), never routed through a model.

    The cost stated is TreasureIQ's own integration cost (D-26 rule 2): no
    line here says or implies a citizen pays it.
    """
    label = MODE_LABELS[ente.access_mode]
    lines = [_COST_TEMPLATES[ente.access_mode].format(label=label)]
    if ente.datasets_on_dati_gov is not None:
        n = ente.datasets_on_dati_gov
        riga = f"Su dati.gov.it risultano {n} dataset di questo ente"
        if ente.dati_gov_probe is not None:
            riga += f" (misurato il {ente.dati_gov_probe.dated.isoformat()})"
        lines.append(riga + ".")
    return lines
