"""Shared isolation for the offline API test suite.

Tests must not share runtime rate-limit state or write into the production
``/live`` mount. The real mount is exercised separately by the opt-in live
E2E suite.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_state(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from treasureiq import api, bandi_live, connettore, mappa_connettore, orari_ufficio
    from treasureiq import registro, scansioni, sonda_live

    api._chiamate_modello.clear()

    for module in (
        api,
        bandi_live,
        connettore,
        mappa_connettore,
        orari_ufficio,
        registro,
        scansioni,
        sonda_live,
    ):
        if hasattr(module, "LIVE_DIR"):
            monkeypatch.setattr(module, "LIVE_DIR", tmp_path)

    if hasattr(bandi_live, "CACHE_DIR"):
        monkeypatch.setattr(bandi_live, "CACHE_DIR", tmp_path / "bandi-criteri")

