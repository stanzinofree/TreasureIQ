"""HTTP API for the TreasureIQ web client.

Serves three things: the citizen's matched opportunities, the readiness report
for a comune, and a mock authentication flow. Everything is computed from the
committed seed snapshot by default, so the whole application runs with no
network access and no API key — which is what makes the demo reproducible for
anyone who clones the repository.

The session model is deliberately thin. There is no user database: a "login"
produces a signed cookie carrying the citizen profile itself. That is adequate
for a mock and, more importantly, it keeps the substitution path honest — when
this is replaced by real SPID/CIE, the profile arrives from the identity
provider's attribute release rather than from our own storage, which is exactly
the shape here.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
import threading
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, Field

from treasureiq.chat.respond import (
    DEFAULT_COMUNE_ISTAT,
    MAX_MESSAGE_CHARS,
    ChatAnswer,
    InfoAnswer,
    approfondisci_nel_comune,
    build_chat_answer,
    RecoveryStats,
    compute_recovery_stats,
)
from treasureiq.chat.intent import Topic
from treasureiq.costo import SOGLIA_RISCOPERTA, costo_comune
from treasureiq.storico import (
    aderenza_fornitori,
    date_censimento,
    panoramica_piattaforme,
    serie,
    sezioni_mancanti,
    vincoli_nazionali,
)
from treasureiq.integration import (
    MODE_LABELS,
    Ente,
    cost_lines,
    diagnosis_lines,
    load_enti,
)
from treasureiq.match.engine import (
    MatchResult,
    Verdict,
    match,
    summarise,
)
from treasureiq.sonda_live import cerca_comuni, comune_per_codice
from treasureiq.readiness import ReadinessReport, score_comune
from treasureiq.recovery import ComuneRecovery, compute_comune_recovery
from treasureiq.schema import CitizenProfile, Confidence, Livello, Opportunity
from treasureiq.stats import (
    APP_VERSION,
    AppStats,
    SystemStatus,
    build_system_status,
    compute_app_stats,
    nearest_comune,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

# In a container the snapshots are mounted rather than copied in, so the path
# cannot be derived from this file's location. Env var wins; the repo-relative
# path is the fallback that makes `uvicorn` work straight from a clone.
DATA_DIR = Path(os.environ.get("TREASUREIQ_DATA_DIR", REPO_ROOT / "data"))
SEED_DIR = DATA_DIR / "seed"
SESSION_COOKIE = "treasureiq_session"

#: Segreto di firma della sessione. Il default esiste perche' `docker compose
#: up` deve funzionare senza configurare niente, ma un segreto noto significa
#: sessioni falsificabili — cioe' un profilo scelto da chi attacca, con l'ISEE
#: e la disabilita' che vuole lui.
#:
#: Percio' fuori da sviluppo l'avvio fallisce invece di proseguire: un default
#: comodo che non si lamenta e' un default che finisce in produzione.
SECRET_DI_PROVA = "treasureiq-demo-not-secret"
SECRET = os.environ.get("TREASUREIQ_SECRET", SECRET_DI_PROVA)
AMBIENTE = os.environ.get("TREASUREIQ_ENV", "sviluppo").strip().lower()

if SECRET == SECRET_DI_PROVA and AMBIENTE not in {"sviluppo", "dev", "test"}:
    raise RuntimeError(
        "TREASUREIQ_SECRET e' rimasto al valore di prova mentre TREASUREIQ_ENV="
        f"{AMBIENTE!r}. Con un segreto noto le sessioni si falsificano: "
        "imposta un segreto vero, oppure dichiara l'ambiente come 'sviluppo'."
    )

#: Comuni whose seed snapshots ship with the repository.
COMUNI = {
    "058003": {
        "nome": "Albano Laziale",
        "ente": "Comune di Albano Laziale",
        "seed": "albano_058003.json",
        # Measured 2026-08-02 via dati.gov.it CKAN package_search. Zero is the
        # finding, not a placeholder.
        "datasets_on_dati_gov": 0,
    },
    "058122": {
        "nome": "Fonte Nuova",
        "ente": "Comune di Fonte Nuova",
        "seed": "fontenuova_058122.json",
        # Measured the same day, the same way, as Albano's zero above:
        #   package_search?q=holder_name:"Comune di Fonte Nuova" -> 5
        # The comparator therefore discriminates on this dimension rather than
        # mirroring Albano — it exposes more services AND publishes nationally,
        # yet fewer of its records yield a recoverable requirement.
        "datasets_on_dati_gov": 5,
    },
    # Ariccia had a snapshot on disk and no entry here, so fifteen records
    # ingested through the HTML connector were invisible to every endpoint.
    # It is also the most instructive comune we have measured: the only one
    # that needed a bespoke connector, and the one whose cost per record is
    # nearly double the others because that connector is amortised over
    # fifteen records instead of forty.
    "058009": {
        "nome": "Ariccia",
        "ente": "Comune di Ariccia",
        "seed": "ariccia_058009.json",
        "datasets_on_dati_gov": 0,
    },
    "046017": {
        # Citta' d'arte con 287 servizi pubblicati: il catalogo piu' ampio fra i comuni letti.
        # Misurato il 5 agosto 2026: 287 servizi via `/wp-json/wp/v2/servizi`,
        # campo requisiti «vuoto», 2 dataset su dati.gov.it.
        "nome": "Lucca",
        "ente": "Comune di Lucca",
        "seed": "lucca_046017.json",
        "datasets_on_dati_gov": 2,
    },
    "062008": {
        # Uno dei 38 comuni italiani che il campo dei requisiti lo compila davvero: senza almeno
    # un comune cosi', TreasureIQ potrebbe solo rispondere «il tuo comune non lo dice».
        # Misurato il 5 agosto 2026: 103 servizi via `/wp-json/wp/v2/servizi`,
        # campo requisiti «compilato», 11 dataset su dati.gov.it.
        "nome": "Benevento",
        "ente": "Comune di Benevento",
        "seed": "benevento_062008.json",
        "datasets_on_dati_gov": 11,
    },
    "074012": {
        # Nessun dataset su dati.gov.it e requisiti non pubblicati: il caso ordinario.
        # Misurato il 5 agosto 2026: 87 servizi via `/wp-json/wp/v2/servizi`,
        # campo requisiti «vuoto», 0 dataset su dati.gov.it.
        "nome": "Ostuni",
        "ente": "Comune di Ostuni",
        "seed": "ostuni_074012.json",
        "datasets_on_dati_gov": 0,
    },
    "083044": {
        # Poche centinaia di abitanti e 81 servizi pubblicati: la copertura non dipende dalla
    # dimensione dell'ente.
        # Misurato il 5 agosto 2026: 81 servizi via `/wp-json/wp/v2/servizi`,
        # campo requisiti «vuoto», 0 dataset su dati.gov.it.
        "nome": "Malvagna",
        "ente": "Comune di Malvagna",
        "seed": "malvagna_083044.json",
        "datasets_on_dati_gov": 0,
    },
    "074010": {
        # Secondo comune con i requisiti compilati, su una piattaforma identica a quella di chi
    # non li compila: la differenza e' una scelta del comune, non del fornitore.
        # Misurato il 5 agosto 2026: 79 servizi via `/wp-json/wp/v2/servizi`,
        # campo requisiti «compilato», 8 dataset su dati.gov.it.
        "nome": "Mesagne",
        "ente": "Comune di Mesagne",
        "seed": "mesagne_074010.json",
        "datasets_on_dati_gov": 8,
    },
}

#: I gruppi in cui Swagger organizza le rotte. Le descrizioni non sono
#: decorative: dicono a chi legge quale contratto sta guardando, perche' le
#: quattro famiglie hanno garanzie diverse — una risposta al cittadino non
#: inventa mai un requisito, una riga di censimento non e' mai una stima.
TAG_METADATA = [
    {
        "name": "Cittadino",
        "description": (
            "Cio' che serve a una persona per sapere se ha diritto a qualcosa. "
            "Nessuna risposta qui contiene un requisito che non sia scritto in un "
            "documento pubblicato: dove la fonte tace, la risposta dice che tace."
        ),
    },
    {
        "name": "Censimento nazionale",
        "description": (
            "La misura di tutti i portali comunali italiani: su quale piattaforma "
            "girano, quanto aderiscono al modello AgID, se pubblicano i requisiti "
            "di accesso. Ogni campo non misurato resta vuoto, mai zero."
        ),
    },
    {
        "name": "Qualita dei dati",
        "description": (
            "Quanto costa leggere cio' che un ente pubblica, e quanto di cio' che "
            "pubblica e' leggibile. Serve a rendere visibile il lavoro che oggi "
            "ricade sul cittadino."
        ),
    },
    {"name": "Sistema", "description": "Stato dei componenti e delle fonti."},
]

app = FastAPI(
    title="TreasureIQ",
    description=(
        "Incrocia gli open data della PA con il profilo del cittadino per "
        "trovare le opportunita' a cui ha davvero accesso.\n\n"
        "**Due garanzie valgono su tutte le rotte.** Un requisito compare solo se "
        "esiste nel documento pubblicato, citato verbatim; e un campo che non "
        "abbiamo potuto misurare resta vuoto invece di essere riempito con uno "
        "zero, perche' su un grafico zero e sconosciuto hanno lo stesso aspetto e "
        "significato opposto."
    ),
    version=APP_VERSION,
    openapi_tags=TAG_METADATA,
    contact={"name": "TreasureIQ", "url": "https://github.com/stanzinofree/TreasureIQ"},
    license_info={"name": "Vedi LICENSE nel repository"},
)

# The web client is served from a different origin in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get(
            "TREASUREIQ_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

serializer = URLSafeSerializer(SECRET, salt="treasureiq-session")


#: Quante domande al modello accettiamo da uno stesso chiamante, e in quanto
#: tempo.
#:
#: La soglia e' bassa di proposito: l'uso legittimo e' una conversazione, non
#: un ciclo. E il motivo non e' il carico — `/api/chat` invoca un modello,
#: quindi ogni richiesta ha un costo in denaro, e senza un limite chiunque
#: conosca l'URL puo' trasformare quel costo in un problema nostro.
LIMITE_MODELLO = int(os.environ.get("TREASUREIQ_LIMITE_MODELLO", "20"))
FINESTRA_MODELLO = int(os.environ.get("TREASUREIQ_FINESTRA_MODELLO", "60"))

#: Chiamate recenti per chiamante. In memoria di proposito: un contatore
#: perfetto vorrebbe uno store condiviso, ma con un processo solo questo
#: ferma l'abuso vero — che e' un ciclo, non un utente distratto — e non
#: aggiunge un'altra cosa da tenere in piedi.
_chiamate_modello: dict[str, list[float]] = defaultdict(list)


def _chiamante(request: Request) -> str:
    """Chi sta chiamando: la sessione se c'e', altrimenti l'indirizzo.

    La sessione viene prima perche' e' piu' precisa di un IP condiviso da un
    ufficio o da una rete mobile: limitare per IP soltanto punirebbe piu'
    persone per colpa di una.
    """
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return f"sessione:{cookie[:32]}"
    client = request.client
    return f"ip:{client.host if client else 'ignoto'}"


def limita_modello(request: Request) -> None:
    """Ferma chi chiama il modello troppo spesso. Solleva 429 con `Retry-After`.

    Il `Retry-After` non e' cortesia formale: senza, un client automatico
    riprova subito e trasforma il limite in un ciclo piu' stretto.
    """
    ora = time.monotonic()
    chiave = _chiamante(request)
    recenti = [t for t in _chiamate_modello[chiave] if ora - t < FINESTRA_MODELLO]
    if len(recenti) >= LIMITE_MODELLO:
        attesa = int(FINESTRA_MODELLO - (ora - recenti[0])) + 1
        _chiamate_modello[chiave] = recenti
        raise HTTPException(
            status_code=429,
            detail=(
                f"Troppe domande in poco tempo: al massimo {LIMITE_MODELLO} "
                f"ogni {FINESTRA_MODELLO} secondi."
            ),
            headers={"Retry-After": str(attesa)},
        )
    recenti.append(ora)
    _chiamate_modello[chiave] = recenti


#: Hand-curated national/regional layer (D-20). Reachable through every comune's
#: AGEVOLAZIONE rail alongside the municipal seed — not tied to any single ISTAT
#: code, so it is loaded once and merged in rather than keyed by comune.
CURATED_SEED = "nazionale_curated.json"

#: Dated cost history, written at ingestion and read here. Absent until an
#: ingestion has run, which `serie()` reports as an empty list.
STORICO_DB = SEED_DIR.parent / "storico.db"


@lru_cache(maxsize=1)
def load_curated_opportunities() -> tuple[Opportunity, ...]:
    """Load the hand-curated national/regional records. Cached, same as the seed."""
    path = SEED_DIR / CURATED_SEED
    if not path.exists():
        return ()
    raw = json.loads(path.read_text("utf-8"))
    return tuple(Opportunity.model_validate(item) for item in raw)


@lru_cache(maxsize=8)
def load_opportunities(codice_istat: str) -> tuple[Opportunity, ...]:
    """Load one comune's snapshot. Cached — the seed is immutable at runtime."""
    meta = COMUNI.get(codice_istat)
    if meta is None:
        raise HTTPException(404, f"Comune {codice_istat} non disponibile")
    path = SEED_DIR / meta["seed"]
    if not path.exists():
        raise HTTPException(
            503,
            f"Snapshot mancante per {meta['nome']}. Esegui prima l'ingestion.",
        )
    raw = json.loads(path.read_text("utf-8"))
    return tuple(Opportunity.model_validate(item) for item in raw) + load_curated_opportunities()


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """What the mock identity provider hands back.

    Mirrors the attribute set SPID actually releases (name, fiscal code,
    residence) plus the means-testing attributes that would come from INPS.
    Keeping the shapes aligned is what makes this a stub rather than a
    throwaway.
    """

    nome: str = "Cittadino"
    codice_fiscale: str | None = None
    comune_istat: str = "058003"
    comune_nome: str = "Albano Laziale"
    eta: int = 38
    isee: Decimal | None = None
    nucleo_familiare: int = 1
    figli_minori: int = 0
    disabilita: bool = False
    employment_status: str | None = None
    interests: list[str] = []


def profile_from_cookie(request_cookie: str | None) -> CitizenProfile | None:
    if not request_cookie:
        return None
    try:
        payload = serializer.loads(request_cookie)
    except BadSignature:
        # Tampered or stale cookie: treat as logged out rather than erroring,
        # so a stale browser session can't wedge someone out of the app.
        logger.info("rejected session cookie with bad signature")
        return None
    try:
        return CitizenProfile.model_validate(payload)
    except Exception:
        logger.info("session cookie did not validate against current schema")
        return None


def current_profile(request: Request) -> CitizenProfile:
    profile = profile_from_cookie(request.cookies.get(SESSION_COOKIE))
    if profile is None:
        raise HTTPException(401, "Nessuna sessione attiva")
    return profile


# --------------------------------------------------------------------------
# Response shapes
# --------------------------------------------------------------------------


class CriterionOut(BaseModel):
    key: str
    label: str
    state: str
    detail: str


class UfficioOut(BaseModel):
    """Where a citizen can ask a human about this record.

    Carries its own provenance: `fonte` is the page the contacts were read
    from and `verificato_il` when that was last checked. A phone number shown
    without either is a number nobody can be held to — and the cost of a wrong
    one is a person standing at a closed counter.
    """

    nome: str
    telefono: str | None
    email: str | None
    orari: str | None
    fonte: str
    verificato_il: date
    #: From IPA, the register every public body must keep current. Separate
    #: from the fields above because it answers a different question and comes
    #: from a different source: this is the channel that legally obliges a
    #: reply, while the phone and the hours above are what the comune posted on
    #: its own page. Each is cited for what it actually knows.
    pec: str | None = None
    pec_fonte: str | None = None
    pec_verificata_il: date | None = None


class MatchOut(BaseModel):
    id: str
    title: str
    summary: str | None
    kind: str
    verdict: str
    verdict_label: str
    headline: str
    relevance: float
    criteria: list[CriterionOut]
    notes: list[str]
    needs_source_check: bool
    source_url: str
    ente: str
    ente_codice_istat: str | None
    #: When this record was last read from the publishing body. Shown to the
    #: citizen because an answer's age is part of the answer: nothing here is
    #: live, and a service that hides how old its snapshot is asks to be
    #: trusted about something it has not checked recently.
    letto_il: datetime
    deadline: date | None
    confidence: str
    livello: str
    #: The publishing body's public desk, when one has been recorded for it.
    #: `None` for national and regional records: `enti.json` holds comuni, and
    #: pointing someone at a municipal URP for an ARERA measure would send
    #: them to a counter that cannot help.
    ufficio: UfficioOut | None


VERDICT_LABELS = {
    Verdict.ELIGIBLE: "Eleggibile",
    Verdict.LIKELY: "Probabile",
    Verdict.UNDETERMINED: "Non verificabile",
    Verdict.NOT_ELIGIBLE: "Escluso",
}


def to_match_out(result: MatchResult) -> MatchOut:
    o = result.opportunity
    return MatchOut(
        id=o.id,
        title=o.title,
        summary=o.summary,
        kind=o.kind.value,
        verdict=result.verdict.value,
        verdict_label=VERDICT_LABELS[result.verdict],
        headline=summarise(result),
        relevance=result.relevance,
        criteria=[
            CriterionOut(key=c.key, label=c.label, state=c.state.value, detail=c.detail)
            for c in result.criteria
        ],
        notes=result.notes,
        needs_source_check=result.needs_source_check,
        source_url=str(o.source.url),
        ente=o.source.ente,
        ente_codice_istat=o.source.ente_codice_istat,
        letto_il=o.source.fetched_at,
        deadline=o.deadline,
        confidence=o.confidence.value,
        livello=o.livello.value,
        ufficio=_ufficio_di(o.source.ente_codice_istat),
    )


def _pec_di(codice_istat: str | None) -> str | None:
    """The body's certified address, from IPA. `None` when we have not read one."""
    if codice_istat is None:
        return None
    ente = load_enti().get(codice_istat)
    return ente.ipa.pec if ente is not None and ente.ipa is not None else None


def _ufficio_di(codice_istat: str | None) -> UfficioOut | None:
    """The publishing body's desk, if one has been recorded and verified.

    Returns `None` rather than a partial guess: no ISTAT code (national and
    regional records), no matching ente, or no URP on file all mean the same
    thing to a citizen — we cannot tell you who to call — and saying so is the
    only honest answer available.
    """
    if codice_istat is None:
        return None
    ente = load_enti().get(codice_istat)
    if ente is None or ente.urp is None:
        return None
    urp = ente.urp
    ipa = ente.ipa
    return UfficioOut(
        nome=urp.nome,
        telefono=urp.telefono,
        email=urp.email,
        orari=urp.orari,
        fonte=str(urp.fonte),
        verificato_il=urp.verificato_il,
        pec=ipa.pec if ipa else None,
        pec_fonte=ipa.fonte if ipa and ipa.pec else None,
        pec_verificata_il=ipa.verificato_il if ipa and ipa.pec else None,
    )


class DimensionOut(BaseModel):
    key: str
    label: str
    earned: float
    weight: int
    evidence: str
    remedy: str


class ReadinessOut(BaseModel):
    ente: str
    codice_istat: str
    score: float
    grade: str
    total_records: int
    dimensions: list[DimensionOut]


class StatsOut(BaseModel):
    """`/api/stats` — the project's own honest headline numbers.

    Every field is computed from ingestion evidence already on disk; a
    number that was never measured is `null`, not an estimate.
    """

    app_version: str
    comuni_measured: int
    records_total: int
    requirements_verified: int
    avg_recovery_seconds: float | None
    sources_below_full_openness_pct: float | None


def to_stats_out(stats: AppStats) -> StatsOut:
    return StatsOut(
        app_version=stats.app_version,
        comuni_measured=stats.comuni_measured,
        records_total=stats.records_total,
        requirements_verified=stats.requirements_verified,
        avg_recovery_seconds=stats.avg_recovery_seconds,
        sources_below_full_openness_pct=stats.sources_below_full_openness_pct,
    )


class SourceStatusOut(BaseModel):
    codice_istat: str
    nome: str
    reachable: bool | None
    last_ingested: datetime | None
    records: int


class SystemComponentOut(BaseModel):
    nome: str
    stato: str
    detail: str


class InternalDatumOut(BaseModel):
    nome: str
    stato: str
    value: str
    detail: str


class StatusOut(BaseModel):
    """`/api/status` — derived from committed seed snapshots, never a live probe.

    Carries the full "Stato sistemi": `sources` (le Fonti) plus `sistemi`
    (TreasureIQ's own components) and `dati_interni` (headline numbers on
    what was recovered). The latter two are additive — `overall` and
    `sources` keep their old shape so existing clients do not break.
    """

    overall: str
    sources: list[SourceStatusOut]
    sistemi: list[SystemComponentOut] = []
    dati_interni: list[InternalDatumOut] = []


def to_status_out(status: SystemStatus) -> StatusOut:
    return StatusOut(
        overall=status.overall,
        sources=[
            SourceStatusOut(
                codice_istat=s.codice_istat,
                nome=s.nome,
                reachable=s.reachable,
                last_ingested=s.last_ingested,
                records=s.records,
            )
            for s in status.sources
        ],
        sistemi=[
            SystemComponentOut(nome=c.nome, stato=c.stato, detail=c.detail)
            for c in status.sistemi
        ],
        dati_interni=[
            InternalDatumOut(nome=d.nome, stato=d.stato, value=d.value, detail=d.detail)
            for d in status.dati_interni
        ],
    )


class ComuneNearbyOut(BaseModel):
    codice_istat: str
    nome: str


class NearbyOut(BaseModel):
    """`/api/comune-nearby` — a device location, never a residency claim.

    R-9: geolocation says where a device is right now, not where its owner
    is resident. `note` exists so this cannot be misread by whoever consumes
    the response next; nothing downstream should ever treat `comune_nearby`
    as an attribute of the citizen.
    """

    comune_nearby: ComuneNearbyOut | None
    note: str


class CostOut(BaseModel):
    """D-17 instrumentation: how closed the comune's own data is.

    This is the civic metric the project exists to surface — deliberately
    the only "cost" left in the response (D-18). Our own chat-turn runtime
    latency is not this project's story and was removed rather than kept
    alongside it. Any field can be `null`: an unmeasured record is not a
    zero-cost one.
    """

    recovery_seconds_total: float | None
    recovery_seconds_avg_comune: float | None
    levels: dict[str, int]


class ChatTurnIn(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    message: str
    #: The exchange so far. The client had been sending this all along and the
    #: model did not declare it, so Pydantic dropped it and every turn started
    #: from nothing — which is why the chat asked for the comune twice and lost
    #: the subject in between.
    history: list[ChatTurnIn] = []
    #: Il comune che il cittadino ha SCELTO da una lista, non quello che una
    #: frase lascia intendere. Quando c'è, vince su qualunque accenno testuale:
    #: un codice ISTAT non ha omonimi, non dipende da come è scritto il nome e
    #: non può essere inventato da un modello. È la via che chiude in un colpo
    #: sia l'ambiguità fra i due Castro sia l'allucinazione del comune.
    comune_istat: str | None = Field(default=None, max_length=6)


class ComuneScelta(BaseModel):
    """Una voce della tendina dei comuni.

    `ha_portale` è falso per i 29 comuni che ISTAT conosce e di cui IPA non
    pubblica il sito (fra cui Roma): vanno mostrati lo stesso — sono comuni
    veri e nasconderli farebbe sembrare l'elenco incompleto — ma chi sceglie
    deve sapere in anticipo che lì non andremo a leggere niente.
    """

    codice_istat: str
    nome: str
    provincia: str
    regione: str
    ha_portale: bool


@app.get("/api/comuni", response_model=list[ComuneScelta], tags=["Cittadino"])
def comuni(q: str = "") -> list[ComuneScelta]:
    """Cerca fra i 7.896 comuni italiani, per far scegliere invece di indovinare.

    L'elenco è quello di ISTAT unito ai siti di IPA (`data/comuni-istat.json`):
    chiuso, pubblico e completo, quindi una query che non trova niente non
    significa "comune non coperto" ma "questo nome non è un comune italiano" —
    un refuso, o il nome di una frazione. La differenza conta, ed è per questo
    che il client deve poterla dire con parole diverse.
    """
    return [
        ComuneScelta(
            codice_istat=c.codice_istat,
            nome=c.nome,
            provincia=c.provincia,
            regione=c.regione,
            ha_portale=bool(c.sito),
        )
        for c in cerca_comuni(q)
    ]


class DocumentOut(BaseModel):
    title: str
    url: str
    #: La descrizione che il comune dà del servizio, verbatim. `None` quando
    #: il record non la porta: un servizio senza descrizione è una lacuna del
    #: comune da mostrare, non un buco da riempire con una frase nostra.
    descrizione: str | None = None
    #: Il giorno in cui abbiamo letto questa pagina.
    verificato_il: date | None = None


class OfficeOut(BaseModel):
    nome: str
    telefono: str | None
    email: str | None
    orari: str | None
    #: The certified address from IPA. Preferred over `email` as the recipient
    #: of a formal request, because a PEC obliges the body to reply while an
    #: ordinary inbox does not — and a citizen asking their comune to publish
    #: its data deserves the channel that cannot simply be ignored.
    pec: str | None = None


class WebResultOut(BaseModel):
    title: str
    url: str
    non_verificato: bool


class ProvaOut(BaseModel):
    """Una riga di «cosa posso confermare». `stato` e' uno fra confermato,
    parziale, mancante — mai una percentuale, che avrebbe l'aria di una
    misura senza esserlo."""

    stato: str
    testo: str


class AzioneOut(BaseModel):
    """Un passo che il cittadino puo' fare adesso. `tipo` dice al client come
    renderlo: apri, chiama, email."""

    testo: str
    url: str | None = None
    tipo: str = "apri"
    dettaglio: str | None = None
    etichetta: str = "Apri"


class InfoOut(BaseModel):
    """The INFORMAZIONE rail's payload (D-19): document/office/coverage plus
    the deterministic diagnosis/cost/web blocks `chat.respond` composed from
    `integration.py` — never a verdict, never criteria, never SPID."""

    document: DocumentOut | None
    office: OfficeOut | None
    coverage_count: int
    diagnosis: list[str]
    integration_cost: list[str]
    web_results: list[WebResultOut]
    #: Vero quando l'ufficio e l'orario qui sopra sono stati letti dal portale
    #: del comune durante questa domanda, non presi da uno snapshot curato
    #: (D-32). Il client ne fa un'etichetta: un dato letto al volo e un dato
    #: verificato non devono avere lo stesso aspetto.
    letto_dal_vivo: bool = False
    #: Provenienza del dato, mai un diritto: «ufficiale», «parziale»,
    #: «non_verificato», «non_pubblicato». Sul rail INFORMAZIONE un verdetto
    #: non esiste e non deve entrare dalla porta di servizio (D-19).
    stato: str = "non_pubblicato"
    #: Le righe di «cosa posso confermare», gia' composte dai campi.
    prove: list[ProvaOut] = []
    #: I passi successivi, scritti per esteso invece che contati.
    azioni: list[AzioneOut] = []
    ente_nome: str | None = None
    # B22 (D-25) — which comune this answer is about, so the segnalazione
    # counter can be attributed correctly. `None` when no ente was resolved
    # (nothing to count the segnalazione against).
    codice_istat: str | None
    ente: str | None


@lru_cache(maxsize=1)
def _enti_by_urp_nome() -> dict[str, tuple[str, str]]:
    """Reverse index: URP display name -> (codice_istat, ente name).

    B22's segnalazione counter needs to know which comune an INFORMAZIONE
    answer concerns, but `InfoAnswer` (chat/respond.py, out of scope for
    this brief) does not carry it. Each ente's URP name in `data/enti.json`
    is unique and is exactly what `respond.py` copies into `info.office.nome`
    — matching on it is an exact lookup, not a guess.
    """
    return {
        ente.urp.nome: (ente.codice_istat, ente.ente)
        for ente in load_enti().values()
        if ente.urp is not None
    }


def to_info_out(info: InfoAnswer) -> InfoOut:
    target = _enti_by_urp_nome().get(info.office.nome) if info.office is not None else None
    return InfoOut(
        letto_dal_vivo=info.letto_dal_vivo,
        stato=info.stato.value,
        ente_nome=info.ente_nome,
        prove=[ProvaOut(stato=p.stato.value, testo=p.testo) for p in info.prove],
        azioni=[
            AzioneOut(
                testo=a.testo,
                url=a.url,
                tipo=a.tipo,
                dettaglio=a.dettaglio,
                etichetta=a.etichetta,
            )
            for a in info.azioni
        ],
        document=(
            DocumentOut(
                title=info.document.title,
                url=info.document.url,
                descrizione=info.document.descrizione,
                verificato_il=info.document.verificato_il,
            )
            if info.document is not None
            else None
        ),
        office=(
            OfficeOut(
                nome=info.office.nome,
                telefono=info.office.telefono,
                email=info.office.email,
                orari=info.office.orari,
                # Resolved from the same `target` the rest of this function
                # uses — a `(codice_istat, ente)` pair keyed by URP name — so
                # the certified address cannot end up belonging to a different
                # body than the office printed beside it.
                pec=_pec_di(target[0]) if target is not None else None,
            )
            if info.office is not None
            else None
        ),
        coverage_count=info.coverage_count,
        diagnosis=info.diagnosis,
        integration_cost=info.integration_cost,
        web_results=[
            WebResultOut(title=r.title, url=r.url, non_verificato=r.non_verificato)
            for r in info.web_results
        ],
        codice_istat=target[0] if target is not None else None,
        ente=target[1] if target is not None else None,
    )


class ProfiloCapitoOut(BaseModel):
    """Quello che TreasureIQ ha capito di te, restituito perche' tu lo veda.

    Serve a due cose diverse e ugualmente importanti. La prima e' fiducia: chi
    legge una risposta su diritti propri deve poter controllare su quali dati
    e' stata costruita. La seconda e' correzione: se abbiamo capito «Pergine
    Valsugana» e intendevi «Pergine Valdarno», l'unico modo perche' tu te ne
    accorga e' vederlo scritto.

    Ogni campo non capito resta vuoto, mai riempito con un valore di comodo.
    """

    comune_nome: str | None = None
    comune_istat: str | None = None
    comune_coperto: bool | None = None
    eta: int | None = None
    isee: str | None = None
    nucleo_familiare: int | None = None
    figli_minori: int | None = None
    disabilita: bool | None = None


class ChatOut(BaseModel):
    reply: str
    #: Cosa abbiamo capito della domanda. Il pannello laterale lo mostra come
    #: filtri attivi, cosi' il cittadino puo' smentirci.
    profilo_capito: ProfiloCapitoOut | None = None
    topic: str
    kind: str
    data_gap: str | None
    needs_clarification: bool
    spid_required: bool
    spid_reason: str | None
    access_mode: str | None
    citizen_effort: int
    info: InfoOut | None
    matches: list[MatchOut]
    cost: CostOut


def _profilo_capito(*, answer, profile, message: str) -> ProfiloCapitoOut:
    """Cosa abbiamo capito, messo in chiaro perche' il cittadino possa smentirlo.

    Le cifre le rilegge l'estrazione deterministica invece di fidarsi di cosa
    ha capito il modello: e' la stessa regola che vale per le soglie nei
    verdetti, e qui serve anche a non mostrare a schermo un'eta' che nessuno
    ha scritto.
    """
    from treasureiq.chat.intent import slot_dal_testo
    from treasureiq.chat.respond import _comune_nominato

    letti = slot_dal_testo(message)
    nominato = _comune_nominato(message)
    comune = nominato or (comune_per_codice(profile.comune_istat) if profile else None)
    coperto = comune.codice_istat in load_enti() if comune is not None else None

    return ProfiloCapitoOut(
        comune_nome=(
            f"{comune.nome} ({comune.provincia})"
            if comune is not None and getattr(comune, "provincia", None)
            else (comune.nome if comune is not None else None)
        ),
        comune_istat=comune.codice_istat if comune is not None else None,
        comune_coperto=coperto,
        eta=letti.get("eta") or (profile.eta if profile else None),
        isee=(
            str(letti["isee"])
            if "isee" in letti
            else (str(profile.isee) if profile and profile.isee is not None else None)
        ),
        nucleo_familiare=profile.nucleo_familiare if profile else None,
        figli_minori=profile.figli_minori if profile else None,
        disabilita=profile.disabilita if profile else None,
    )


def to_readiness_out(report: ReadinessReport) -> ReadinessOut:
    return ReadinessOut(
        ente=report.ente,
        codice_istat=report.codice_istat,
        score=report.score,
        grade=report.grade.value,
        total_records=report.total_records,
        dimensions=[
            DimensionOut(
                key=d.key,
                label=d.label,
                earned=round(d.earned, 1),
                weight=d.weight,
                evidence=d.evidence,
                remedy=d.remedy,
            )
            for d in report.dimensions
        ],
    )


class RecordCostOut(BaseModel):
    id: str
    title: str
    recovery_level: str | None
    extraction_seconds: float | None
    pdfs_linked: int | None
    pdfs_opened: int | None
    pdfs_skipped: int | None
    chars_processed: int | None
    requirements_recovered: int | None


class RecoveryOut(BaseModel):
    """D-16 recovery cost for one comune.

    `typed_records` and `unmeasured_records` are deliberately separate fields:
    the first cost nothing because the comune published them structured, the
    second we simply never measured. See `recovery.py` — merging them would
    flatter a comune for data we never looked at.
    """

    ente: str
    codice_istat: str
    records_total: int
    typed_records: int
    recovered_records: int
    unmeasured_records: int
    levels: dict[str, int]
    seconds_total: float | None
    seconds_avg: float | None
    pdfs_linked_total: int
    pdfs_opened_total: int
    pdfs_skipped_total: int
    requirements_recovered_total: int
    records: list[RecordCostOut]


def to_recovery_out(report: ComuneRecovery) -> RecoveryOut:
    return RecoveryOut(
        ente=report.ente,
        codice_istat=report.codice_istat,
        records_total=report.records_total,
        typed_records=report.typed_records,
        recovered_records=report.recovered_records,
        unmeasured_records=report.unmeasured_records,
        levels=report.levels,
        seconds_total=(
            round(report.seconds_total, 2) if report.seconds_total is not None else None
        ),
        seconds_avg=(
            round(report.seconds_avg, 2) if report.seconds_avg is not None else None
        ),
        pdfs_linked_total=report.pdfs_linked_total,
        pdfs_opened_total=report.pdfs_opened_total,
        pdfs_skipped_total=report.pdfs_skipped_total,
        requirements_recovered_total=report.requirements_recovered_total,
        records=[
            RecordCostOut(
                id=r.id,
                title=r.title,
                recovery_level=r.recovery_level,
                extraction_seconds=(
                    round(r.extraction_seconds, 2)
                    if r.extraction_seconds is not None
                    else None
                ),
                pdfs_linked=r.pdfs_linked,
                pdfs_opened=r.pdfs_opened,
                pdfs_skipped=r.pdfs_skipped,
                chars_processed=r.chars_processed,
                requirements_recovered=r.requirements_recovered,
            )
            for r in report.records
        ],
    )


class IntegrationOut(BaseModel):
    """Per-ente integration cost + access mode (D-21), for the `/dati` page.

    `diagnosis` and `integration_cost` are the SAME deterministic sentences
    `integration.py`'s `diagnosis_lines`/`cost_lines` compose for the chat's
    INFORMAZIONE rail (D-24) — rendered here, not re-authored, so the two
    surfaces never say something different about the same measurement.
    `datasets_on_dati_gov` stays `None` where it was never probed (Marino):
    the client must render that as "non misurato", never as `0` (D-16).
    """

    ente: str
    codice_istat: str
    access_mode: str
    label: str
    probe_dated: date
    probe_method: str
    diagnosis: list[str]
    integration_cost: list[str]
    datasets_on_dati_gov: int | None
    benchmark_342: int | None
    segnalazioni_count: int
    #: Where a request to open this body's data should be addressed. The
    #: certified address first: a PEC obliges a reply, an ordinary inbox does
    #: not, and someone who has just read how little their comune publishes
    #: deserves the channel that cannot be ignored.
    pec: str | None = None
    urp_email: str | None = None
    urp_nome: str | None = None


def to_integration_out(ente: Ente) -> IntegrationOut:
    counts = _read_segnalazioni()
    return IntegrationOut(
        ente=ente.ente,
        codice_istat=ente.codice_istat,
        access_mode=ente.access_mode.value,
        label=MODE_LABELS[ente.access_mode],
        probe_dated=ente.probe.dated,
        probe_method=ente.probe.method,
        diagnosis=diagnosis_lines(ente),
        integration_cost=cost_lines(ente),
        datasets_on_dati_gov=ente.datasets_on_dati_gov,
        benchmark_342=ente.calendario_raccolta_open_data_comuni,
        segnalazioni_count=counts.get(ente.codice_istat, 0),
        pec=ente.ipa.pec if ente.ipa is not None else None,
        urp_email=ente.urp.email if ente.urp is not None else None,
        urp_nome=ente.urp.nome if ente.urp is not None else None,
    )


# --------------------------------------------------------------------------
# Segnalazioni (B22, D-25) — the form generates a request, it does not send
# one. This is only ever an anonymous per-comune counter: no IP, no session,
# no citizen text is ever stored here.
# --------------------------------------------------------------------------

SEGNALAZIONI_PATH = DATA_DIR / "segnalazioni.json"
_segnalazioni_lock = threading.Lock()
_segnalazioni_memory: dict[str, int] = {}
_segnalazioni_memory_only = False


def _read_segnalazioni() -> dict[str, int]:
    if _segnalazioni_memory_only:
        return dict(_segnalazioni_memory)
    if not SEGNALAZIONI_PATH.exists():
        return {}
    try:
        return json.loads(SEGNALAZIONI_PATH.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _increment_segnalazione(codice_istat: str) -> int:
    """Increment the counter for one comune and persist it.

    Read-modify-write is serialized by `_segnalazioni_lock`; the write
    itself is atomic (temp file + `os.replace` on the same filesystem), so
    concurrent requests cannot corrupt `data/segnalazioni.json`.

    Falls back to an in-memory counter, with a logged warning, if the data
    directory turns out to be read-only (e.g. a `./data:/data:ro` compose
    mount) — the count still works for the running process, it just does
    not survive a restart. The bare-metal demo on :8010 has a writable
    `data/`, where it does.
    """
    global _segnalazioni_memory_only
    with _segnalazioni_lock:
        if _segnalazioni_memory_only:
            _segnalazioni_memory[codice_istat] = _segnalazioni_memory.get(codice_istat, 0) + 1
            return _segnalazioni_memory[codice_istat]

        counts = _read_segnalazioni()
        counts[codice_istat] = counts.get(codice_istat, 0) + 1
        try:
            tmp_path = SEGNALAZIONI_PATH.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(counts), encoding="utf-8")
            os.replace(tmp_path, SEGNALAZIONI_PATH)
        except OSError:
            logger.warning(
                "data dir not writable, falling back to in-memory segnalazioni counter"
            )
            _segnalazioni_memory_only = True
            _segnalazioni_memory.update(counts)
        return counts[codice_istat]


class SegnalazioneIn(BaseModel):
    codice_istat: str


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@app.get("/api/health", tags=["Sistema"])
def health() -> dict[str, object]:
    return {"status": "ok", "comuni": list(COMUNI)}


@app.post("/api/session", response_model=CitizenProfile, tags=["Cittadino"])
def create_session(body: LoginRequest, response: Response) -> CitizenProfile:
    """Mock SPID login. Issues a signed cookie carrying the profile.

    No credentials are checked, by design — this stands in for an identity
    provider we cannot integrate with in a hackathon timeframe. The README says
    so plainly; a demo that implied real SPID would be the dishonest choice.
    """
    from treasureiq.schema import EmploymentStatus, TargetGroup

    profile = CitizenProfile(
        codice_fiscale=body.codice_fiscale,
        comune_istat=body.comune_istat,
        comune_nome=body.comune_nome,
        eta=body.eta,
        isee=body.isee,
        nucleo_familiare=body.nucleo_familiare,
        figli_minori=body.figli_minori,
        disabilita=body.disabilita,
        employment_status=(
            EmploymentStatus(body.employment_status) if body.employment_status else None
        ),
        interests=[TargetGroup(i) for i in body.interests],
    )
    response.set_cookie(
        SESSION_COOKIE,
        serializer.dumps(json.loads(profile.model_dump_json())),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 8,
    )
    return profile


@app.delete("/api/session", tags=["Cittadino"])
def end_session(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "logged_out"}


@app.get("/api/me", response_model=CitizenProfile, tags=["Cittadino"])
def me(profile: CitizenProfile = Depends(current_profile)) -> CitizenProfile:
    return profile


@app.get("/api/opportunities", response_model=list[MatchOut], tags=["Cittadino"])
def opportunities(
    profile: CitizenProfile = Depends(current_profile),
    include_ineligible: bool = False,
) -> list[MatchOut]:
    """Rank the citizen's own comune's opportunities for them."""
    records = list(load_opportunities(profile.comune_istat))
    results = match(records, profile, include_ineligible=include_ineligible)
    return [to_match_out(r) for r in results]


class VoceCostoOut(BaseModel):
    chiave: str
    etichetta: str
    valore: float
    evidenza: str


class CostoOut(BaseModel):
    """What one comune costs TreasureIQ to keep readable (D-26 rule 2).

    Never presented as a bill to the citizen and never as a grade for the
    administration: it is our own integration cost, and the components are
    shipped with it so a reader can check the arithmetic rather than trust the
    total.
    """

    ente: str
    codice_istat: str
    modo: str
    scoperta_il: date
    eta_scoperta_giorni: int
    scoperta_scaduta: bool
    soglia_riscoperta_giorni: int
    record_totali: int
    record_strutturati: int
    record_recuperati_da_prosa: int
    record_non_recuperati: int
    #: Reported as evidence, deliberately absent from the score: wall-clock
    #: time measures our machine and their file sizes as much as their
    #: openness.
    secondi_recupero: float | None
    costo_totale: float
    costo_per_record: float | None
    voci: list[VoceCostoOut]


def _costo_out(codice_istat: str) -> CostoOut:
    meta = COMUNI.get(codice_istat)
    ente = load_enti().get(codice_istat)
    if meta is None or ente is None:
        raise HTTPException(404, f"Comune {codice_istat} non disponibile")
    records = [r for r in load_opportunities(codice_istat) if r.livello is Livello.COMUNALE]
    c = costo_comune(ente=ente, records=records)
    return CostoOut(
        ente=c.ente,
        codice_istat=c.codice_istat,
        modo=c.modo.value,
        scoperta_il=c.scoperta_il,
        eta_scoperta_giorni=c.eta_scoperta_giorni,
        scoperta_scaduta=c.scoperta_scaduta,
        soglia_riscoperta_giorni=SOGLIA_RISCOPERTA.days,
        record_totali=c.record_totali,
        record_strutturati=c.record_strutturati,
        record_recuperati_da_prosa=c.record_recuperati_da_prosa,
        record_non_recuperati=c.record_non_recuperati,
        secondi_recupero=c.secondi_recupero,
        costo_totale=c.costo_totale,
        costo_per_record=c.costo_per_record,
        voci=[
            VoceCostoOut(
                chiave=v.chiave, etichetta=v.etichetta, valore=v.valore, evidenza=v.evidenza
            )
            for v in c.voci
        ],
    )


class FonteAggregata(BaseModel):
    tipo: str
    enti: int
    servizi: int


class PanoramicaOut(BaseModel):
    """Aggregate figures for the monitoring dashboard.

    Aggregate on purpose. Broken down per comune, the same numbers answered a
    question nobody asked — the reader of a status page wants to know the shape
    of what we hold, not to compare three municipalities line by line. The
    per-comune detail lives on /dati, where comparing them is the point.
    """

    servizi_totali: int
    enti_totali: int
    comuni_misurati: int
    #: Grouped by the tier that published them, which is the division that
    #: changes what a record means: a national measure applies everywhere, a
    #: municipal one only where it was published.
    fonti: list[FonteAggregata]
    criteri_strutturati: int
    criteri_recuperati: int
    criteri_non_recuperati: int
    ultimo_accesso: datetime | None
    #: How many comuni sit on each rung of D-21, keyed by access mode.
    gradini: dict[str, int]


@app.get("/api/panoramica", response_model=PanoramicaOut, tags=["Qualita dei dati"])
def panoramica() -> PanoramicaOut:
    """One aggregate picture of everything read so far."""
    tutti: list[Opportunity] = []
    for istat in COMUNI:
        tutti.extend(load_opportunities(istat))
    # `load_opportunities` merges the curated national layer into every comune,
    # so the same national record arrives once per comune. Deduplicated by id,
    # or a two-comune deployment would report twice the sources it has.
    unici = {r.id: r for r in tutti}.values()

    per_tipo: dict[str, dict[str, set | int]] = {}
    ETICHETTA = {
        Livello.NAZIONALE: "Stato",
        Livello.REGIONALE: "Regioni",
        Livello.COMUNALE: "Comuni",
    }
    for r in unici:
        etichetta = ETICHETTA.get(r.livello, "Altro")
        voce = per_tipo.setdefault(etichetta, {"enti": set(), "servizi": 0})
        voce["enti"].add(r.source.ente)  # type: ignore[union-attr]
        voce["servizi"] = int(voce["servizi"]) + 1  # type: ignore[arg-type]

    fonti = [
        FonteAggregata(tipo=t, enti=len(v["enti"]), servizi=int(v["servizi"]))  # type: ignore[arg-type]
        for t, v in sorted(per_tipo.items(), key=lambda kv: -int(kv[1]["servizi"]))
    ]

    comunali = [r for r in unici if r.livello is Livello.COMUNALE]
    strutturati = sum(
        1
        for r in comunali
        if r.confidence is Confidence.DECLARED and not r.requirements.is_empty
    )
    recuperati = sum(1 for r in comunali if (r.requirements_recovered or 0) > 0)

    letture = [r.source.fetched_at for r in unici if r.source.fetched_at]
    enti = load_enti()
    gradini: dict[str, int] = {}
    for istat in COMUNI:
        ente = enti.get(istat)
        if ente is not None:
            gradini[ente.access_mode.value] = gradini.get(ente.access_mode.value, 0) + 1

    return PanoramicaOut(
        servizi_totali=len(unici),
        enti_totali=sum(f.enti for f in fonti),
        comuni_misurati=len([i for i in COMUNI if i in enti]),
        fonti=fonti,
        criteri_strutturati=strutturati,
        criteri_recuperati=recuperati,
        criteri_non_recuperati=len(comunali) - strutturati - recuperati,
        ultimo_accesso=max(letture) if letture else None,
        gradini=gradini,
    )


@app.get("/api/costo", response_model=list[CostoOut], tags=["Qualita dei dati"])
def costi() -> list[CostoOut]:
    """Every measured comune's integration cost, cheapest per record first.

    Ordered by cost *per record* rather than by total: a comune needing a
    bespoke connector for fifteen records is more expensive to read than one
    needing a parser for forty, and the total hides exactly that.
    """
    out = [_costo_out(istat) for istat in COMUNI if istat in load_enti()]
    return sorted(out, key=lambda c: (c.costo_per_record is None, c.costo_per_record or 0))


class PuntoStoricoOut(BaseModel):
    rilevato_il: date
    codice_istat: str
    ente: str
    modo: str
    record_totali: int
    record_strutturati: int
    record_recuperati: int
    record_non_recuperati: int
    costo_totale: float
    costo_per_record: float | None
    scoperta_scaduta: bool


@app.get("/api/storico", response_model=list[PuntoStoricoOut], tags=["Qualita dei dati"])
def storico(codice_istat: str | None = None) -> list[PuntoStoricoOut]:
    """Dated cost observations, oldest first.

    Written at ingestion and read here: an empty list means no ingestion has
    recorded anything yet, which is the ordinary state of a fresh checkout and
    not a fault. Callers render an empty history rather than an error, because
    a chart with no points is the honest picture of a history nobody kept.
    """
    punti = serie(STORICO_DB, codice_istat=codice_istat)
    return [
        PuntoStoricoOut(
            rilevato_il=p.rilevato_il,
            codice_istat=p.codice_istat,
            ente=p.ente,
            modo=p.modo,
            record_totali=p.record_totali,
            record_strutturati=p.record_strutturati,
            record_recuperati=p.record_recuperati,
            record_non_recuperati=p.record_non_recuperati,
            costo_totale=p.costo_totale,
            costo_per_record=p.costo_per_record,
            scoperta_scaduta=p.scoperta_scaduta,
        )
        for p in punti
    ]


@app.get("/api/readiness/{codice_istat}", response_model=ReadinessOut, tags=["Qualita dei dati"])
def readiness(codice_istat: str) -> ReadinessOut:
    """Public — no session required. The score is about the comune, not a person."""
    meta = COMUNI.get(codice_istat)
    if meta is None:
        raise HTTPException(404, f"Comune {codice_istat} non disponibile")
    records = list(load_opportunities(codice_istat))
    report = score_comune(
        ente=meta["ente"],
        codice_istat=codice_istat,
        records=records,
        datasets_on_dati_gov=meta["datasets_on_dati_gov"],
    )
    return to_readiness_out(report)


@app.get("/api/readiness", response_model=list[ReadinessOut], tags=["Qualita dei dati"])
def readiness_all() -> list[ReadinessOut]:
    return [readiness(istat) for istat in COMUNI]


@app.get("/api/recovery/{codice_istat}", response_model=RecoveryOut, tags=["Qualita dei dati"])
def recovery(codice_istat: str) -> RecoveryOut:
    """Public — what it cost to make this comune's data machine-readable."""
    meta = COMUNI.get(codice_istat)
    if meta is None:
        raise HTTPException(404, f"Comune {codice_istat} non disponibile")
    return to_recovery_out(
        compute_comune_recovery(
            ente=meta["ente"],
            codice_istat=codice_istat,
            records=list(load_opportunities(codice_istat)),
        )
    )


@app.get("/api/recovery", response_model=list[RecoveryOut], tags=["Qualita dei dati"])
def recovery_all() -> list[RecoveryOut]:
    return [recovery(istat) for istat in COMUNI]


@app.get("/api/integration", response_model=list[IntegrationOut], tags=["Qualita dei dati"])
def integration() -> list[IntegrationOut]:
    """Public — per-ente access mode + integration cost (D-21).

    `load_enti()` returns the cached snapshot of `data/enti.json`, which is
    committed, static data mounted read-only at runtime — refresh it by
    re-running ingestion, never by editing the file under the API. The route
    holds no reference of its own, so a restart picks up a refreshed snapshot
    without this module changing.
    """
    return [to_integration_out(ente) for ente in load_enti().values()]


@app.get("/api/stats", response_model=StatsOut, tags=["Qualita dei dati"])
def stats() -> StatsOut:
    """Public headline numbers for the landing page — no session required.

    A missing snapshot for one comune must not take the whole endpoint down
    with a 503 (unlike `load_opportunities`, used by session-scoped routes
    where a missing seed really is an error): it just contributes zero
    records to the aggregate, the same way `build_system_status` treats it.
    """
    records_by_comune: dict[str, list[Opportunity]] = {}
    for istat, meta in COMUNI.items():
        path = SEED_DIR / meta["seed"]
        if not path.exists():
            records_by_comune[istat] = []
            continue
        raw = json.loads(path.read_text("utf-8"))
        records_by_comune[istat] = [Opportunity.model_validate(item) for item in raw]
    return to_stats_out(compute_app_stats(comuni=COMUNI, records_by_comune=records_by_comune))


@app.get("/api/status", response_model=StatusOut, tags=["Sistema"])
def status() -> StatusOut:
    """Public system status — derived from disk, never a live probe (see `stats.py`)."""
    return to_status_out(build_system_status(comuni=COMUNI, seed_dir=SEED_DIR))


@app.get("/api/comune-nearby", response_model=NearbyOut, tags=["Cittadino"])
def comune_nearby(lat: float, lon: float) -> NearbyOut:
    """Resolve a device coordinate to a supported comune.

    R-9: this is location, not residency. See `NearbyOut` and
    `stats.nearest_comune` — nothing here may be used to assert who the
    citizen is or where they live.
    """
    centroid = nearest_comune(lat=lat, lon=lon)
    return NearbyOut(
        comune_nearby=(
            ComuneNearbyOut(codice_istat=centroid.codice_istat, nome=centroid.nome)
            if centroid is not None
            else None
        ),
        note="posizione, non residenza",
    )


@app.post("/api/segnalazioni", tags=["Cittadino"])
def create_segnalazione(body: SegnalazioneIn) -> dict[str, int]:
    """Record that a citizen generated an open-data request for one comune.

    Anonymous by construction (D-25): the only input accepted is the ISTAT
    code, nothing else is read from the request body or from `request`
    itself — no IP, no cookie, no citizen text.
    """
    if body.codice_istat not in load_enti():
        raise HTTPException(404, f"Comune {body.codice_istat} non disponibile")
    return {body.codice_istat: _increment_segnalazione(body.codice_istat)}


@app.get("/api/segnalazioni", tags=["Cittadino"])
def get_segnalazioni() -> dict[str, int]:
    """Public per-comune counter — itself the published fact D-25 asks for."""
    return _read_segnalazioni()


class ApprofondimentoIn(BaseModel):
    #: Carried over from the answer that prompted this, so no model runs here
    #: and the same request always yields the same result.
    topic: str


class PaginaWebOut(BaseModel):
    title: str
    url: str
    #: Always true. These pages were found by a search engine, not read from a
    #: dataset: nothing here was parsed, quote-gated or checked against the
    #: requirements the way a record is. The flag exists so the interface can
    #: never present one as if it had been.
    non_verificato: bool = True


class ApprofondimentoOut(BaseModel):
    esito: str
    comune_nome: str
    matches: list[MatchOut]
    #: Last rung of the access ladder (D-21 `M6_web_aperto`), reached only when
    #: the comune's structured records turned up nothing.
    pagine: list[PaginaWebOut] = []


@app.post("/api/approfondimento", response_model=ApprofondimentoOut, tags=["Cittadino"], dependencies=[Depends(limita_modello)])
def approfondimento(body: ApprofondimentoIn, request: Request) -> ApprofondimentoOut:
    """Ask explicitly what the citizen's own comune published on a topic.

    The ordinary answer already searches municipal and national records
    together, so this does not reach anything the first pass missed. It exists
    to state the thing the first pass leaves unsaid: when the only result was
    a national measure, nothing told the citizen whether their comune had
    published anything of its own. An absence nobody states reads as an
    absence nobody looked for.
    """
    try:
        topic = Topic(body.topic)
    except ValueError:
        raise HTTPException(422, f"Tema non riconosciuto: {body.topic}") from None

    profile = profile_from_cookie(request.cookies.get(SESSION_COOKIE))
    # No session, no comune. Defaulting to Albano here meant the button "e il
    # mio comune?" answered about somebody else's comune, in a sentence naming
    # it — the same unfounded residency claim the hero used to make, and worse
    # because this one is dressed as a finding. When we do not know, the honest
    # answer is to ask.
    comune_istat = profile.comune_istat if profile is not None else None
    if comune_istat is None:
        return ApprofondimentoOut(
            esito=(
                "Per controllare cosa ha pubblicato il tuo comune devo sapere "
                "qual è. Scrivimelo nella chat, oppure usa «Usa la mia "
                "posizione» qui sopra."
            ),
            comune_nome="",
            matches=[],
            pagine=[],
        )
    meta = COMUNI.get(comune_istat)
    comune_nome = meta["nome"] if meta else "Il tuo comune"
    records = list(load_opportunities(comune_istat))

    results, esito, pagine = approfondisci_nel_comune(
        records=records,
        topic=topic,
        profile=profile,
        comune_nome=comune_nome,
        # Carries the comune's own web host, so pages belonging to a different
        # municipality can be dropped: institutional is not the same as yours.
        ente=load_enti().get(comune_istat),
    )
    return ApprofondimentoOut(
        esito=esito,
        comune_nome=comune_nome,
        matches=[to_match_out(r) for r in results],
        pagine=[PaginaWebOut(title=p.title, url=p.url) for p in pagine],
    )


@app.post("/api/chat", response_model=ChatOut, tags=["Cittadino"], dependencies=[Depends(limita_modello)])
async def chat(body: ChatIn, request: Request) -> ChatOut:
    """Anonymous-by-default chat over Albano public data.

    The model never decides eligibility here (D-01 in `.kapi/spec.md`): it
    only classifies the citizen's free text into a closed intent schema
    (`treasureiq.chat.intent`) and, at the end, rephrases Italian strings
    `match/engine.py` already produced (`treasureiq.chat.respond`). Every
    criterion state and verdict in `matches` traces back to the engine
    untouched. If the model is unavailable, `build_chat_answer` falls back
    to the deterministic `summarise()` text rather than letting this route
    fail.
    """
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Il messaggio non può essere vuoto.")
    if len(message) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            422,
            f"Il messaggio è troppo lungo (massimo {MAX_MESSAGE_CHARS} caratteri).",
        )

    profile = profile_from_cookie(request.cookies.get(SESSION_COOKIE))

    # Un comune scelto esplicitamente decide quali record si guardano, e se non
    # ne abbiamo non se ne guardano affatto. Prima i record erano sempre quelli
    # del comune coperto: chiesto «c'è un aiuto per la mensa?» avendo scelto
    # Camposampiero, uscivano tre agevolazioni di Albano come se riguardassero
    # chi aveva domandato. Non è una risposta imprecisa, è la risposta di un
    # altro comune — e il sistema sapeva già di non essere lì (R-9).
    scelto = body.comune_istat if body.comune_istat in COMUNI else None
    comune_istat = scelto or (
        profile.comune_istat if profile is not None else DEFAULT_COMUNE_ISTAT
    )
    comune_coperto = body.comune_istat is None or body.comune_istat in COMUNI
    records = list(load_opportunities(comune_istat)) if comune_coperto else []

    answer: ChatAnswer = await build_chat_answer(
        message=message,
        profile=profile,
        records=records,
        # Only what the citizen said. Feeding our own replies back in would let
        # one answer become the input to the next, and a mistake made once
        # would then justify itself for the rest of the conversation.
        storia=[t.content for t in body.history if t.role == "user"],
        # Una scelta esplicita batte qualunque inferenza: vedi ChatIn.
        comune_istat=body.comune_istat,
        comune_coperto=comune_coperto,
    )

    # `records` sono quelli del comune coperto (oggi Albano). Su una risposta
    # letta dal vivo parlano di un altro comune, e la striscia dei costi
    # mostrava «media di recupero dati da PDF del comune: 3 s» sotto un orario
    # di Camposampiero: un numero vero, riferito a qualcun altro, che passa
    # per una misura di ciò che si sta leggendo. Nessuna misura è meglio di
    # una misura che riguarda un'altra cosa (D-16).
    letta_dal_vivo = answer.info is not None and answer.info.letto_dal_vivo
    stats = (
        RecoveryStats(seconds_total=None, seconds_avg_comune=None, levels={})
        if letta_dal_vivo
        else compute_recovery_stats(
            comune_records=records,
            answer_records=[r.opportunity for r in answer.matches],
        )
    )

    return ChatOut(
        reply=answer.reply,
        profilo_capito=_profilo_capito(answer=answer, profile=profile, message=body.message),
        topic=answer.topic.value,
        kind=answer.kind.value,
        data_gap=answer.data_gap,
        needs_clarification=answer.needs_clarification,
        spid_required=answer.spid_required,
        spid_reason=answer.spid_reason,
        access_mode=answer.access_mode,
        # AGEVOLAZIONE answers never set this (D-29 is an INFORMAZIONE-rail
        # concept there); 0 residual actions, not a fabricated estimate.
        citizen_effort=answer.citizen_effort or 0,
        info=to_info_out(answer.info) if answer.info is not None else None,
        matches=[to_match_out(r) for r in answer.matches],
        cost=CostOut(
            recovery_seconds_total=stats.seconds_total,
            recovery_seconds_avg_comune=stats.seconds_avg_comune,
            levels=stats.levels,
        ),
    )


class PiattaformaOut(BaseModel):
    """Quanti comuni girano su una piattaforma, e quanto pubblicano."""

    piattaforma: str
    comuni: int
    popolazione: int | None = None
    servizi: int
    con_catalogo: int
    #: In quante regioni compare, e quanto pesa nella sua principale. Un
    #: prodotto nazionale sta ovunque; una piattaforma regionale sta in una
    #: regione sola, ed è una differenza che il conteggio dei comuni nasconde.
    regioni: int = 0
    regione_prima: str | None = None
    comuni_prima: int = 0


class FornitoreOut(BaseModel):
    """L'aderenza al modello AgID di un fornitore, con la sua base di misura.

    `base_misura` non è un dettaglio da nascondere in fondo: raggruppare
    `modello_intero` e `schema_esposto` in una classifica sola mette ultimo il
    fornitore più conforme, perché la sua API serializza due box su undici.
    """

    piattaforma: str
    base_misura: str | None = None
    comuni: int
    misurati: int
    aderenza_media: float | None = None
    aderenza_minima: float | None = None
    impronte: int


class SezioneOut(BaseModel):
    sezione: str
    manca_su: int
    misurati: int


class VincoliOut(BaseModel):
    """Quanti comuni pubblicano i requisiti di accesso, e quanti no.

    `assente` e' una scelta del fornitore, `vuoto` una del comune: tenerli
    distinti e' la ragione per cui questa misura vale qualcosa.
    """

    stato: str
    comuni: int


class CensimentoOut(BaseModel):
    rilevato_il: date | None = None
    date_disponibili: list[date] = []
    piattaforme: list[PiattaformaOut] = []
    fornitori: list[FornitoreOut] = []
    sezioni_mancanti: list[SezioneOut] = []
    vincoli: list[VincoliOut] = []


@app.get("/api/censimento", response_model=CensimentoOut, tags=["Censimento nazionale"])
def censimento() -> CensimentoOut:
    """Il censimento dei portali comunali, nell'ultimo rilevamento.

    Vuoto finché nessuno sweep è stato registrato, che è lo stato normale di
    un checkout fresco: le pagine disegnano un censimento vuoto invece di un
    errore, perché non aver ancora misurato non è un guasto.
    """
    giorni = date_censimento(STORICO_DB)
    if not giorni:
        return CensimentoOut()
    ultimo = giorni[-1]
    return CensimentoOut(
        rilevato_il=ultimo,
        date_disponibili=giorni,
        piattaforme=[PiattaformaOut(**r) for r in _senza(panoramica_piattaforme(STORICO_DB))],
        fornitori=[FornitoreOut(**r) for r in _senza(aderenza_fornitori(STORICO_DB))],
        sezioni_mancanti=[SezioneOut(**r) for r in sezioni_mancanti(STORICO_DB)],
        vincoli=[VincoliOut(**r) for r in vincoli_nazionali(STORICO_DB)],
    )


def _senza(righe: list[dict]) -> list[dict]:
    """Toglie la data ripetuta su ogni riga: sta già in testa alla risposta."""
    return [{k: v for k, v in r.items() if k != "rilevato_il"} for r in righe]


class ConnettoreOut(BaseModel):
    """Una piattaforma e quanto sappiamo leggerla, oggi."""

    piattaforma: str
    #: `catalogo` = sappiamo contarne i servizi. `modello` = sappiamo leggerne
    #: le schede col modello AgID. `firma` = la riconosciamo e basta.
    livello: str
    firma: str
    rotta_servizi: str | None = None
    note: str | None = None


@app.get("/api/connettori", response_model=list[ConnettoreOut], tags=["Censimento nazionale"])
def connettori() -> list[ConnettoreOut]:
    """Il catalogo delle sonde: cosa sappiamo leggere, piattaforma per piattaforma.

    Costruito dal codice, non da una tabella scritta a mano: una piattaforma
    che perde la sua declinazione sparisce da qui il giorno stesso, invece di
    restare in vetrina a promettere una lettura che non facciamo più.
    """
    from treasureiq.ingest.censimento import _ROTTE_SERVIZI
    from treasureiq.ingest.modello_agid import DECLINAZIONI
    from treasureiq.ingest.piattaforma import Piattaforma

    fuori_catalogo = {Piattaforma.IGNOTA, Piattaforma.NON_MISURATA}
    esiti: list[ConnettoreOut] = []
    for piattaforma in Piattaforma:
        if piattaforma in fuori_catalogo:
            continue
        rotta = _ROTTE_SERVIZI.get(piattaforma)
        ha_modello = piattaforma.value in DECLINAZIONI
        wp = piattaforma is Piattaforma.WP_DESIGN_COMUNI
        if ha_modello and (rotta or wp):
            livello = "modello"
        elif wp:
            livello = "catalogo"
        else:
            livello = "firma"
        esiti.append(
            ConnettoreOut(
                piattaforma=piattaforma.value,
                livello=livello,
                firma="riconosciuta",
                rotta_servizi=(rotta[0] if rotta else ("/wp-json/wp/v2/servizi" if wp else None)),
                note=(
                    "campi tipizzati: si distingue esposto da compilato"
                    if wp
                    else None
                ),
            )
        )
    return esiti
