"""The MVP opportunity snapshots are an explicit, reversible fallback."""

from __future__ import annotations

from treasureiq import api
from treasureiq.schema import Opportunity


def test_seed_fallback_can_be_disabled_for_chat(monkeypatch) -> None:
    monkeypatch.setenv("TREASUREIQ_LEGACY_SEED_FALLBACK", "0")
    seed = Opportunity.model_construct(id="seed")
    monkeypatch.setattr(api, "load_opportunities", lambda _istat: (seed,))

    assert api.legacy_seed_fallback_enabled() is False
    assert api.records_per_chat("058003") == []


def test_seed_fallback_is_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TREASUREIQ_LEGACY_SEED_FALLBACK", raising=False)
    seed = Opportunity.model_construct(id="seed")
    monkeypatch.setattr(api, "load_opportunities", lambda _istat: (seed,))

    assert api.legacy_seed_fallback_enabled() is True
    assert api.records_per_chat("058003") == [seed]
