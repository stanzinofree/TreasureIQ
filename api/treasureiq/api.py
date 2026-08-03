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
import threading
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel

from treasureiq.chat.respond import (
    DEFAULT_COMUNE_ISTAT,
    MAX_MESSAGE_CHARS,
    ChatAnswer,
    InfoAnswer,
    approfondisci_nel_comune,
    build_chat_answer,
    compute_recovery_stats,
)
from treasureiq.chat.intent import Topic
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
from treasureiq.readiness import ReadinessReport, score_comune
from treasureiq.recovery import ComuneRecovery, compute_comune_recovery
from treasureiq.schema import CitizenProfile, Opportunity
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

# Demo secret. Real deployments must set TREASUREIQ_SECRET; this default exists
# so `docker compose up` works out of the box for a reviewer, and is safe only
# because the session carries no privilege — just a self-declared profile.
SECRET = os.environ.get("TREASUREIQ_SECRET", "treasureiq-demo-not-secret")

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
}

app = FastAPI(
    title="TreasureIQ",
    description=(
        "Incrocia gli open data della PA con il profilo del cittadino per "
        "trovare le opportunita' a cui ha davvero accesso."
    ),
    version=APP_VERSION,
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


#: Hand-curated national/regional layer (D-20). Reachable through every comune's
#: AGEVOLAZIONE rail alongside the municipal seed — not tied to any single ISTAT
#: code, so it is loaded once and merged in rather than keyed by comune.
CURATED_SEED = "nazionale_curated.json"


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


class ChatIn(BaseModel):
    message: str


class DocumentOut(BaseModel):
    title: str
    url: str


class OfficeOut(BaseModel):
    nome: str
    telefono: str | None
    email: str | None
    orari: str | None


class WebResultOut(BaseModel):
    title: str
    url: str
    non_verificato: bool


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
        document=(
            DocumentOut(title=info.document.title, url=info.document.url)
            if info.document is not None
            else None
        ),
        office=(
            OfficeOut(
                nome=info.office.nome,
                telefono=info.office.telefono,
                email=info.office.email,
                orari=info.office.orari,
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


class ChatOut(BaseModel):
    reply: str
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


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "comuni": list(COMUNI)}


@app.post("/api/session", response_model=CitizenProfile)
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


@app.delete("/api/session")
def end_session(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "logged_out"}


@app.get("/api/me", response_model=CitizenProfile)
def me(profile: CitizenProfile = Depends(current_profile)) -> CitizenProfile:
    return profile


@app.get("/api/opportunities", response_model=list[MatchOut])
def opportunities(
    profile: CitizenProfile = Depends(current_profile),
    include_ineligible: bool = False,
) -> list[MatchOut]:
    """Rank the citizen's own comune's opportunities for them."""
    records = list(load_opportunities(profile.comune_istat))
    results = match(records, profile, include_ineligible=include_ineligible)
    return [to_match_out(r) for r in results]


@app.get("/api/readiness/{codice_istat}", response_model=ReadinessOut)
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


@app.get("/api/readiness", response_model=list[ReadinessOut])
def readiness_all() -> list[ReadinessOut]:
    return [readiness(istat) for istat in COMUNI]


@app.get("/api/recovery/{codice_istat}", response_model=RecoveryOut)
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


@app.get("/api/recovery", response_model=list[RecoveryOut])
def recovery_all() -> list[RecoveryOut]:
    return [recovery(istat) for istat in COMUNI]


@app.get("/api/integration", response_model=list[IntegrationOut])
def integration() -> list[IntegrationOut]:
    """Public — per-ente access mode + integration cost (D-21).

    `load_enti()` returns the cached snapshot of `data/enti.json`, which is
    committed, static data mounted read-only at runtime — refresh it by
    re-running ingestion, never by editing the file under the API. The route
    holds no reference of its own, so a restart picks up a refreshed snapshot
    without this module changing.
    """
    return [to_integration_out(ente) for ente in load_enti().values()]


@app.get("/api/stats", response_model=StatsOut)
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


@app.get("/api/status", response_model=StatusOut)
def status() -> StatusOut:
    """Public system status — derived from disk, never a live probe (see `stats.py`)."""
    return to_status_out(build_system_status(comuni=COMUNI, seed_dir=SEED_DIR))


@app.get("/api/comune-nearby", response_model=NearbyOut)
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


@app.post("/api/segnalazioni")
def create_segnalazione(body: SegnalazioneIn) -> dict[str, int]:
    """Record that a citizen generated an open-data request for one comune.

    Anonymous by construction (D-25): the only input accepted is the ISTAT
    code, nothing else is read from the request body or from `request`
    itself — no IP, no cookie, no citizen text.
    """
    if body.codice_istat not in load_enti():
        raise HTTPException(404, f"Comune {body.codice_istat} non disponibile")
    return {body.codice_istat: _increment_segnalazione(body.codice_istat)}


@app.get("/api/segnalazioni")
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


@app.post("/api/approfondimento", response_model=ApprofondimentoOut)
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
    comune_istat = profile.comune_istat if profile is not None else DEFAULT_COMUNE_ISTAT
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


@app.post("/api/chat", response_model=ChatOut)
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
    comune_istat = profile.comune_istat if profile is not None else DEFAULT_COMUNE_ISTAT
    records = list(load_opportunities(comune_istat))

    answer: ChatAnswer = await build_chat_answer(
        message=message, profile=profile, records=records
    )

    stats = compute_recovery_stats(
        comune_records=records,
        answer_records=[r.opportunity for r in answer.matches],
    )

    return ChatOut(
        reply=answer.reply,
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
