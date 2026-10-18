"""Bounded AT canary orchestration: no network in these tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from treasureiq import registro_cli


def _args(checkpoint: Path, **over: object) -> argparse.Namespace:
    base = dict(checkpoint=checkpoint, resume=False, delay=0.0, max_runs=4,
                max_seconds=60, dry_run=False)
    base.update(over)
    return argparse.Namespace(**base)


def test_at_canary_avanza_sulla_ladder_e_congela_la_coda(tmp_path, monkeypatch):
    checkpoint = tmp_path / "at-canary.json"
    candidati = [{"istat": f"{n:06d}", "dominio": f"{n}.example.it"} for n in range(9)]
    chiamati: list[str] = []
    monkeypatch.setattr(registro_cli, "_at_canary_candidati", lambda: candidati)
    monkeypatch.setattr(registro_cli, "_at_canary_cluster", lambda _d, _i: None)
    monkeypatch.setattr(registro_cli, "_scansiona_uno", lambda istat: (chiamati.append(istat) or ("ok", "ok")))

    assert registro_cli.cmd_at_canary(_args(checkpoint, max_runs=2)) == 0
    dati = json.loads(checkpoint.read_text("utf-8"))
    assert chiamati == [c["istat"] for c in candidati]
    assert dati["run_eseguiti"] == 2
    assert dati["rung"] == 2  # 3 -> 6, next 12
    assert dati["selezione"] == candidati


def test_at_canary_pausa_dominio_dopo_due_errori(tmp_path, monkeypatch):
    checkpoint = tmp_path / "at-canary.json"
    candidati = [{"istat": f"{n:06d}", "dominio": "fragile.example.it"} for n in range(3)]
    monkeypatch.setattr(registro_cli, "_at_canary_candidati", lambda: candidati)
    monkeypatch.setattr(registro_cli, "_at_canary_cluster", lambda _d, _i: None)
    monkeypatch.setattr(registro_cli, "_scansiona_uno", lambda _istat: ("errore", "rete caduta"))

    assert registro_cli.cmd_at_canary(_args(checkpoint, max_runs=1)) == registro_cli.BOOTSTRAP_ERRORI
    dati = json.loads(checkpoint.read_text("utf-8"))
    assert "fragile.example.it" in dati["pause_dominio"]
    assert dati["errori_dominio"]["fragile.example.it"] == 3
    assert dati["rung"] == 0


def test_at_canary_stop_non_fetches(tmp_path, monkeypatch):
    checkpoint = tmp_path / "at-canary.json"
    stop = checkpoint.with_suffix(".stop")
    stop.write_text("stop", "utf-8")
    monkeypatch.setattr(registro_cli, "_at_canary_candidati", lambda: [{"istat": "000001", "dominio": "x.it"}])
    monkeypatch.setattr(registro_cli, "_scansiona_uno", lambda _istat: (_ for _ in ()).throw(AssertionError("fetch")))

    assert registro_cli.cmd_at_canary(_args(checkpoint)) == registro_cli.BOOTSTRAP_STOP


def test_at_canary_salva_dopo_ogni_comune(tmp_path, monkeypatch):
    checkpoint = tmp_path / "at-canary.json"
    candidati = [{"istat": "000001", "dominio": "a.it"}, {"istat": "000002", "dominio": "b.it"}]
    monkeypatch.setattr(registro_cli, "_at_canary_candidati", lambda: candidati)
    monkeypatch.setattr(registro_cli, "_at_canary_cluster", lambda _d, _i: None)
    monkeypatch.setattr(registro_cli, "_scansiona_uno", lambda _istat: ("ok", "ok"))

    def verifica_checkpoint(_secondi):
        assert json.loads(checkpoint.read_text("utf-8"))["completati"] == ["000001"]

    monkeypatch.setattr(registro_cli.time, "sleep", verifica_checkpoint)
    assert registro_cli.cmd_at_canary(_args(checkpoint, delay=1.0, max_runs=1)) == 0


def test_at_canary_ferma_e_chiede_rianalisi_oltre_dieci_percento(tmp_path, monkeypatch):
    checkpoint = tmp_path / "at-canary.json"
    candidati = [{"istat": f"00000{n}", "dominio": f"{n}.it"} for n in range(3)]
    esiti = iter([("ok", "ok"), ("ok", "ok"), ("errore", "rete caduta")])
    monkeypatch.setattr(registro_cli, "_at_canary_candidati", lambda: candidati)
    monkeypatch.setattr(registro_cli, "_at_canary_cluster", lambda _d, _i: None)
    monkeypatch.setattr(registro_cli, "_scansiona_uno", lambda _istat: next(esiti))

    assert registro_cli.cmd_at_canary(_args(checkpoint, max_runs=2)) == registro_cli.BOOTSTRAP_ERRORI
    dati = json.loads(checkpoint.read_text("utf-8"))
    assert dati["run_eseguiti"] == 1  # no automatic replay without reanalysis


def test_at_canary_timeout_non_consuma_budget_semantico(tmp_path, monkeypatch):
    checkpoint = tmp_path / "at-canary.json"
    candidati = [{"istat": f"00000{n}", "dominio": f"{n}.it"} for n in range(6)]
    esiti = iter(
        [("errore", "The read operation timed out")] * 3
        + [("ok", "ok")] * 6
    )
    monkeypatch.setattr(registro_cli, "_at_canary_candidati", lambda: candidati)
    monkeypatch.setattr(registro_cli, "_at_canary_cluster", lambda _d, _i: None)
    monkeypatch.setattr(registro_cli, "_scansiona_uno", lambda _istat: next(esiti))

    assert registro_cli.cmd_at_canary(_args(checkpoint, max_runs=2)) == 0
    dati = json.loads(checkpoint.read_text("utf-8"))
    assert dati["run_eseguiti"] == 2
    assert dati["errori_semantici"] == []


def test_at_canary_resume_conta_i_batch_per_invocazione(tmp_path, monkeypatch):
    checkpoint = tmp_path / "at-canary.json"
    candidati = [{"istat": f"00000{n}", "dominio": f"{n}.it"} for n in range(6)]
    monkeypatch.setattr(registro_cli, "_at_canary_candidati", lambda: candidati)
    monkeypatch.setattr(registro_cli, "_at_canary_cluster", lambda _d, _i: None)
    monkeypatch.setattr(registro_cli, "_scansiona_uno", lambda _istat: ("ok", "ok"))

    assert registro_cli.cmd_at_canary(_args(checkpoint, max_runs=1)) == 0
    assert registro_cli.cmd_at_canary(_args(checkpoint, resume=True, max_runs=1)) == 0

    dati = json.loads(checkpoint.read_text("utf-8"))
    assert dati["run_eseguiti"] == 2
    assert len(dati["completati"]) == 6
