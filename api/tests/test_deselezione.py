"""Regression tests for explicit profile-field removal in the match engine."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from treasureiq.match.engine import CriterionState, Verdict, evaluate
from treasureiq.schema import CitizenProfile, Opportunity

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "albano_058003.json"
SEED = [Opportunity.model_validate(item) for item in json.loads(SEED_PATH.read_text("utf-8"))]
BASE_PROFILE = CitizenProfile(comune_istat="058003", comune_nome="Albano Laziale", eta=30, isee=Decimal("15000"), nucleo_familiare=4)


def _first_with(**field_values) -> Opportunity:
    for opportunity in SEED:
        if all(getattr(opportunity.requirements, key) == value for key, value in field_values.items()):
            return opportunity
    raise AssertionError(f"no seed opportunity with requirements {field_values}")


@pytest.mark.parametrize("criterion_key,field_name,opportunity", [("isee", "isee", _first_with(isee_max=Decimal("20000.00"))), ("eta", "eta", _first_with(eta_min=18))])
def test_deselezionare_un_campo_non_diventa_esclusione(criterion_key, field_name, opportunity):
    with_field = evaluate(opportunity, BASE_PROFILE)
    assert next(c for c in with_field.criteria if c.key == criterion_key).state is CriterionState.MET
    without_field = evaluate(opportunity, BASE_PROFILE.model_copy(update={field_name: None}))
    criterion = next(c for c in without_field.criteria if c.key == criterion_key)
    assert criterion.state is CriterionState.UNKNOWN_PROFILE
    assert without_field.verdict is not Verdict.NOT_ELIGIBLE


def test_deselezionare_il_nucleo_familiare_non_diventa_esclusione():
    opportunity = SEED[0].model_copy(update={"requirements": SEED[0].requirements.model_copy(update={"nucleo_min": 3})})
    with_field = evaluate(opportunity, BASE_PROFILE)
    assert next(c for c in with_field.criteria if c.key == "nucleo").state is CriterionState.MET
    without_field = evaluate(opportunity, BASE_PROFILE.model_copy(update={"nucleo_familiare": None}))
    assert next(c for c in without_field.criteria if c.key == "nucleo").state is CriterionState.UNKNOWN_PROFILE
    assert without_field.verdict is not Verdict.NOT_ELIGIBLE


def test_deselezione_non_lava_un_ostacolo_reale():
    opportunity = _first_with(isee_max=Decimal("20000.00"))
    result = evaluate(opportunity, BASE_PROFILE.model_copy(update={"isee": Decimal("50000")}))
    assert next(c for c in result.criteria if c.key == "isee").state is CriterionState.NOT_MET
    assert result.verdict is Verdict.NOT_ELIGIBLE
