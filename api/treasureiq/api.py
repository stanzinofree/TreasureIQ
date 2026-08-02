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
from datetime import date
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
    build_chat_answer,
    compute_recovery_stats,
)
from treasureiq.match.engine import (
    MatchResult,
    Verdict,
    match,
    summarise,
)
from treasureiq.readiness import ReadinessReport, score_comune
from treasureiq.schema import CitizenProfile, Opportunity

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
    version="0.1.0",
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
    return tuple(Opportunity.model_validate(item) for item in raw)


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
    deadline: date | None
    confidence: str


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
        deadline=o.deadline,
        confidence=o.confidence.value,
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


class ChatOut(BaseModel):
    reply: str
    topic: str
    data_gap: str | None
    needs_clarification: bool
    spid_required: bool
    spid_reason: str | None
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
        data_gap=answer.data_gap,
        needs_clarification=answer.needs_clarification,
        spid_required=answer.spid_required,
        spid_reason=answer.spid_reason,
        matches=[to_match_out(r) for r in answer.matches],
        cost=CostOut(
            recovery_seconds_total=stats.seconds_total,
            recovery_seconds_avg_comune=stats.seconds_avg_comune,
            levels=stats.levels,
        ),
    )
