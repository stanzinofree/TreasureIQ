"""Regressione per la cache del connettore con timestamp non leggibile."""

from __future__ import annotations

from pathlib import Path

import pytest

import treasureiq.connettore as connettore_mod
from treasureiq.connettore import EsitoConnettore, _da_store, _in_store


def test_cache_con_letto_il_malformato_degrada_ad_assente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    esito = EsitoConnettore(
        codice_istat="097015",
        piattaforma="openpa",
        letto_il="non e una data ISO",
    )
    _in_store(esito)

    assert _da_store(esito.codice_istat) is None
