"""D-46 regression: removing a profile field must never flip a verdict negative.

The UI lets a citizen deselect a field they entered (e.g. remove their ISEE
after typing it). Removing information is not the same as failing a
criterion, and the engine must reflect that: a criterion the citizen has no
data for resolves to UNKNOWN_PROFILE, never NOT_MET, and the overall verdict
degrades toward UNDETERMINED/LIKELY rather than flipping to NOT_ELIGIBLE.

Each case here starts from a real opportunity in the committed Albano Laziale
seed, sets the one profile field that criterion reads so it evaluates MET,
then clears that same field and asserts the criterion is UNKNOWN_PROFILE and
the verdict never becomes NOT_ELIGIBLE.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from treasureiq.api import app
from treasureiq.match.engine import CriterionState, Verdict, evaluate
from treasureiq.schema import CitizenProfile, Opportunity

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = REPO_ROOT / "data" / "seed" / "albano_058003.json"


def _load_seed() -> list[Opportunity]:
    raw = json.loads(SEED_PATH.read_text("utf-8"))
    return [Opportunity.model_validate(item) for item in raw]


def _first_with(opportunities: list[Opportunity], **field_values) -> Opportunity:
    """First seed opportunity whose requirements match every field given."""
    for opp in opportunities:
        req = opp.requirements
        if all(getattr(req, key) == value for key, value in field_values.items()):
            return opp
    raise AssertionError(f"no seed opportunity with requirements {field_values}")


SEED = _load_seed()

BASE_PROFILE = CitizenProfile(
    comune_istat="058003",
    comune_nome="Albano Laziale",
    eta=30,
    isee=Decimal("15000"),
    nucleo_familiare=4,
)


@pytest.mark.parametrize(
    "criterion_key,field_name,opportunity",
    [
        ("isee", "isee", _first_with(SEED, isee_max=Decimal("20000.00"))),
        ("eta", "eta", _first_with(SEED, eta_min=18)),
    ],
)
def test_deselezionare_un_campo_del_profilo_non_diventa_esclusione(
    criterion_key, field_name, opportunity
):
    """A criterion that was MET with the field set becomes UNKNOWN_PROFILE,
    never NOT_MET, once the field is cleared — and the verdict never flips to
    NOT_ELIGIBLE."""
    result_with_field = evaluate(opportunity, BASE_PROFILE)
    criterion_with_field = next(
        c for c in result_with_field.criteria if c.key == criterion_key
    )
    assert criterion_with_field.state is CriterionState.MET
    assert result_with_field.verdict is not Verdict.NOT_ELIGIBLE

    profile_without_field = BASE_PROFILE.model_copy(update={field_name: None})
    result_without_field = evaluate(opportunity, profile_without_field)
    criterion_without_field = next(
        c for c in result_without_field.criteria if c.key == criterion_key
    )
    assert criterion_without_field.state is CriterionState.UNKNOWN_PROFILE
    assert result_without_field.verdict is not Verdict.NOT_ELIGIBLE
    assert result_without_field.verdict is not None


def test_deselezionare_il_nucleo_familiare_non_diventa_esclusione():
    """Same guard for nucleo_familiare. No seed record declares nucleo_min,
    so this synthesises one on top of a real opportunity's requirements
    rather than inventing an unrelated record from scratch."""
    base_opportunity = SEED[0]
    opportunity = base_opportunity.model_copy(
        update={
            "requirements": base_opportunity.requirements.model_copy(
                update={"nucleo_min": 3}
            )
        }
    )

    result_with_field = evaluate(opportunity, BASE_PROFILE)
    criterion_with_field = next(
        c for c in result_with_field.criteria if c.key == "nucleo"
    )
    assert criterion_with_field.state is CriterionState.MET
    assert result_with_field.verdict is not Verdict.NOT_ELIGIBLE

    profile_without_field = BASE_PROFILE.model_copy(update={"nucleo_familiare": None})
    result_without_field = evaluate(opportunity, profile_without_field)
    criterion_without_field = next(
        c for c in result_without_field.criteria if c.key == "nucleo"
    )
    assert criterion_without_field.state is CriterionState.UNKNOWN_PROFILE
    assert result_without_field.verdict is not Verdict.NOT_ELIGIBLE


def test_deselezione_non_inverte_mai_un_criterio_gia_not_met():
    """Sanity check on the other direction: clearing a field must not turn a
    genuine NOT_MET into something friendlier either — UNKNOWN_PROFILE only
    applies when the field disappears, not as a way to launder a real
    rejection. This locks in that a NOT_MET criterion needs the field
    present, so a future change can't accidentally reuse the None-guard to
    swallow real blockers."""
    opportunity = _first_with(SEED, isee_max=Decimal("20000.00"))
    over_threshold_profile = BASE_PROFILE.model_copy(update={"isee": Decimal("50000")})

    result = evaluate(opportunity, over_threshold_profile)
    criterion = next(c for c in result.criteria if c.key == "isee")
    assert criterion.state is CriterionState.NOT_MET
    assert result.verdict is Verdict.NOT_ELIGIBLE


def test_dimentica_campo_endpoint_preserva_i_campi_non_toccati():
    """HTTP-level regression for POST /api/session/dimentica.

    A full re-`POST /api/session` rebuilds the profile from LoginRequest's
    defaults, so replaying it after a removal would silently reset
    nucleo_familiare to 1 and drop isee — fields the citizen never touched.
    /api/session/dimentica must null only the field named in `campo`.
    """
    client = TestClient(app)
    login = client.post(
        "/api/session",
        json={
            "comune_istat": "058003",
            "comune_nome": "Albano Laziale",
            "eta": 38,
            "isee": 15000,
            "nucleo_familiare": 3,
            "interests": [],
        },
    )
    assert login.status_code == 200

    dimentica_eta = client.post("/api/session/dimentica", json={"campo": "eta"})
    assert dimentica_eta.status_code == 200

    profile = client.get("/api/me").json()
    assert profile["eta"] is None
    assert profile["nucleo_familiare"] == 3
    assert profile["isee"] == "15000"

    dimentica_nucleo = client.post(
        "/api/session/dimentica", json={"campo": "nucleo_familiare"}
    )
    assert dimentica_nucleo.status_code == 200
    assert dimentica_nucleo.json()["nucleo_familiare"] is None


def test_dimentica_campo_endpoint_non_flippa_il_verdetto_a_not_eligible():
    """Ties the HTTP endpoint to the engine — the actual D-46 path a citizen
    exercises through the chip's × button, not just a hand-built
    CitizenProfile. A criterion MET on the profile /api/session produced
    becomes UNKNOWN_PROFILE, never NOT_MET, once /api/session/dimentica
    clears that same field through the live session."""
    client = TestClient(app)
    client.post(
        "/api/session",
        json={
            "comune_istat": "058003",
            "comune_nome": "Albano Laziale",
            "eta": 30,
            "isee": 15000,
            "nucleo_familiare": 4,
            "interests": [],
        },
    )

    # login can only ever set disabilita to a concrete bool (LoginRequest has
    # no None option — the exact hard-default gap this fix closes elsewhere),
    # so an unrelated disabilita_required requirement on the seed record
    # would flip NOT_MET regardless of nucleo. Cleared here so the only
    # requirement under test is nucleo_min.
    base_opportunity = SEED[0]
    opportunity = base_opportunity.model_copy(
        update={
            "requirements": base_opportunity.requirements.model_copy(
                update={"nucleo_min": 3, "disabilita_required": None}
            )
        }
    )

    profile_with_field = CitizenProfile.model_validate(client.get("/api/me").json())
    result_with_field = evaluate(opportunity, profile_with_field)
    criterion_with_field = next(
        c for c in result_with_field.criteria if c.key == "nucleo"
    )
    assert criterion_with_field.state is CriterionState.MET
    assert result_with_field.verdict is not Verdict.NOT_ELIGIBLE

    client.post("/api/session/dimentica", json={"campo": "nucleo_familiare"})
    profile_without_field = CitizenProfile.model_validate(client.get("/api/me").json())
    result_without_field = evaluate(opportunity, profile_without_field)
    criterion_without_field = next(
        c for c in result_without_field.criteria if c.key == "nucleo"
    )
    assert criterion_without_field.state is CriterionState.UNKNOWN_PROFILE
    assert result_without_field.verdict is not Verdict.NOT_ELIGIBLE
