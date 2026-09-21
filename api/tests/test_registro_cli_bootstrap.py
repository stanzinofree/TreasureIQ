"""Tests for the `registro_cli bootstrap` subcommand orchestration.

The real fetch (`_scansiona_uno` -> leggi_connettore) is stubbed: these tests
cover selection wiring, dry-run, checkpoint/resume, the stop-file, and exit
codes — never the network. The stub also lets us assert the command itself
writes nothing outside the checkpoint file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from treasureiq import registro_cli


def _catalog(dir_: Path, codice: str, piattaforma: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{codice}.json").write_text(
        json.dumps({"services": {"s1": {"provider_platform": piattaforma, "source_url": "u"}}}),
        "utf-8",
    )


def _scena(tmp_path: Path) -> Path:
    cat = tmp_path / "catalog"
    for pi, plat in enumerate(["hgate", "comweb", "openpa", "openweb", "comunibootstrapitalia"]):
        for j in range(3):
            _catalog(cat, f"{pi:02d}{j:04d}", plat)
    return cat


def _args(cat: Path, **over) -> argparse.Namespace:
    base = dict(
        canary=False, per_piattaforma=2, limit=None, delay=0.0,
        checkpoint=None, resume=False, dry_run=False,
        catalog=cat, db=Path("/nonexistent/storico.db"),
    )
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture(autouse=True)
def _stub(monkeypatch, tmp_path):
    """Queue = all catalogued codes; nothing initialised; fetch is a no-op stub."""
    cat = tmp_path / "catalog"

    def fake_coda(_db):
        return sorted(p.stem for p in cat.glob("*.json")) if cat.exists() else []

    monkeypatch.setattr(registro_cli, "_comuni_da_censimento", fake_coda)
    monkeypatch.setattr(registro_cli, "_connettore_inizializzati", lambda: set())
    calls: list[str] = []

    def fake_scan(istat):
        calls.append(istat)
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", fake_scan)
    return calls


def test_dry_run_non_esegue_fetch(tmp_path, _stub):
    cat = _scena(tmp_path)
    rc = registro_cli.cmd_bootstrap(_args(cat, dry_run=True))
    assert rc == registro_cli.BOOTSTRAP_OK
    assert _stub == []  # no fetch at all


def test_canary_seleziona_dieci_ignora_limit(tmp_path, _stub):
    cat = _scena(tmp_path)
    rc = registro_cli.cmd_bootstrap(_args(cat, canary=True, limit=3))
    assert rc == registro_cli.BOOTSTRAP_OK
    assert len(_stub) == 10  # 2 x 5, --limit ignored


def test_limit_lotto(tmp_path, _stub):
    cat = _scena(tmp_path)
    rc = registro_cli.cmd_bootstrap(_args(cat, limit=4))
    assert rc == registro_cli.BOOTSTRAP_OK
    assert len(_stub) == 4


def test_checkpoint_scritto_dopo_ogni_comune(tmp_path, _stub):
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp))
    dati = json.loads(cp.read_text("utf-8"))
    assert len(dati["completati"]) == 3
    assert dati["totale_candidati"] == 15
    assert dati["errori"] == []


def test_resume_salta_completati(tmp_path, _stub):
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    # First lotto of 4.
    registro_cli.cmd_bootstrap(_args(cat, limit=4, checkpoint=cp))
    fatti_prima = list(_stub)
    assert len(fatti_prima) == 4
    _stub.clear()
    # Resume with a bigger lotto: only the remaining are fetched again.
    registro_cli.cmd_bootstrap(_args(cat, limit=8, checkpoint=cp, resume=True))
    assert set(_stub).isdisjoint(fatti_prima)  # never re-fetch a completed comune
    assert len(_stub) == 4  # 8 selected - 4 already done


def test_resume_ritenta_gli_errori(tmp_path, monkeypatch):
    """A comune that errored must be retried on --resume, and clear on success.

    The blocker this guards: errored comuni were added to `completati` and thus
    skipped forever. They must stay out of `completati`, be retried, and drop
    out of `errori` once they succeed.
    """
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"

    def fake_coda(_db):
        return sorted(p.stem for p in cat.glob("*.json"))

    monkeypatch.setattr(registro_cli, "_comuni_da_censimento", fake_coda)
    monkeypatch.setattr(registro_cli, "_connettore_inizializzati", lambda: set())

    # First run: the first selected comune errors; the rest are ok.
    primo = registro_cli.bootstrap_sel.lotto(
        registro_cli.bootstrap_sel.seleziona(cat, set(fake_coda(None)), set()), 3
    )
    guasto = primo[0]

    stato_per_run = {"fallisci": True}

    def fake_scan(istat):
        if istat == guasto and stato_per_run["fallisci"]:
            return "errore", f"{istat} — errore"
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", fake_scan)

    rc1 = registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp))
    assert rc1 == registro_cli.BOOTSTRAP_ERRORI
    dati1 = json.loads(cp.read_text("utf-8"))
    assert guasto not in dati1["completati"]  # errored -> NOT completed
    assert dati1["errori"] == [guasto]

    # Resume: the connector now succeeds for the previously-failed comune.
    stato_per_run["fallisci"] = False
    fetched: list[str] = []
    orig = fake_scan

    def fake_scan2(istat):
        fetched.append(istat)
        return orig(istat)

    monkeypatch.setattr(registro_cli, "_scansiona_uno", fake_scan2)
    rc2 = registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp, resume=True))
    assert rc2 == registro_cli.BOOTSTRAP_OK
    assert fetched == [guasto]  # only the failed comune retried, others skipped
    dati2 = json.loads(cp.read_text("utf-8"))
    assert guasto in dati2["completati"]
    assert dati2["errori"] == []  # cleared on successful retry


def test_checkpoint_esistente_senza_resume_rifiuta(tmp_path, _stub):
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    cp.write_text(json.dumps({"completati": [], "errori": [], "avviato_il": "x"}), "utf-8")
    rc = registro_cli.cmd_bootstrap(_args(cat, limit=2, checkpoint=cp))
    assert rc == 2  # refuse to clobber
    assert _stub == []


def test_stop_file_ferma_e_codice_dedicato(tmp_path, monkeypatch):
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    stop = cp.with_suffix(".stop")

    def fake_coda(_db):
        return sorted(p.stem for p in cat.glob("*.json"))

    monkeypatch.setattr(registro_cli, "_comuni_da_censimento", fake_coda)
    monkeypatch.setattr(registro_cli, "_connettore_inizializzati", lambda: set())
    done: list[str] = []

    def fake_scan(istat):
        done.append(istat)
        stop.write_text("stop", "utf-8")  # ask to halt after the first comune
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", fake_scan)
    rc = registro_cli.cmd_bootstrap(_args(cat, limit=6, checkpoint=cp))
    assert rc == registro_cli.BOOTSTRAP_STOP
    assert len(done) == 1  # stopped between comuni, before the second


def test_exit_code_errori(tmp_path, monkeypatch):
    cat = _scena(tmp_path)

    def fake_coda(_db):
        return sorted(p.stem for p in cat.glob("*.json"))

    monkeypatch.setattr(registro_cli, "_comuni_da_censimento", fake_coda)
    monkeypatch.setattr(registro_cli, "_connettore_inizializzati", lambda: set())

    def fake_scan(istat):
        return ("errore", f"{istat} — errore") if istat.endswith("0000") else ("ok", f"{istat} — ok")

    monkeypatch.setattr(registro_cli, "_scansiona_uno", fake_scan)
    rc = registro_cli.cmd_bootstrap(_args(cat, limit=6))
    assert rc == registro_cli.BOOTSTRAP_ERRORI


@pytest.mark.parametrize("over", [
    {"delay": -1.0},
    {"limit": 0},
    {"per_piattaforma": 0},
])
def test_validazione_argomenti(tmp_path, _stub, over):
    cat = _scena(tmp_path)
    rc = registro_cli.cmd_bootstrap(_args(cat, **over))
    assert rc == 2
    assert _stub == []  # rejected before any fetch


def test_catalogo_invariato_dopo_run(tmp_path, _stub):
    cat = _scena(tmp_path)
    prima = {p.name: p.read_text("utf-8") for p in cat.glob("*.json")}
    registro_cli.cmd_bootstrap(_args(cat, limit=5))
    dopo = {p.name: p.read_text("utf-8") for p in cat.glob("*.json")}
    assert prima == dopo  # selection reads the catalog, never writes it
