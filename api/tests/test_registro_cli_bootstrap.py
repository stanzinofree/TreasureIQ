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
        canary=False, per_piattaforma=2, limit=None, max_per_run=None,
        piattaforma=None, delay=0.0,
        checkpoint=None, resume=False, retry_vuoti=False, dry_run=False,
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


def test_lotto_per_piattaforma_riprende_senza_ripetere(tmp_path, _stub):
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    assert registro_cli.cmd_bootstrap(_args(cat, piattaforma="hgate", max_per_run=2, checkpoint=cp)) == 0
    assert len(_stub) == 2
    assert len(json.loads(cp.read_text("utf-8"))["selezione"]) == 3
    assert registro_cli.cmd_bootstrap(_args(cat, max_per_run=2, checkpoint=cp, resume=True)) == 0
    assert len(_stub) == 3
    assert len(set(_stub)) == 3


def test_checkpoint_scritto_dopo_ogni_comune(tmp_path, _stub):
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp))
    dati = json.loads(cp.read_text("utf-8"))
    assert len(dati["arruolati"]) == 3  # stub returns ok -> enrolled
    assert dati["vuoti"] == []
    assert dati["totale_candidati"] == 15
    assert dati["errori"] == []


def test_resume_salta_completati(tmp_path, monkeypatch):
    """Resume continues the FROZEN selection, never re-fetching a completed comune."""
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"

    def fake_coda(_db):
        return sorted(p.stem for p in cat.glob("*.json"))

    monkeypatch.setattr(registro_cli, "_comuni_da_censimento", fake_coda)
    monkeypatch.setattr(registro_cli, "_connettore_inizializzati", lambda: set())

    stop = cp.with_suffix(".stop")
    n = {"i": 0}
    fatti1: list[str] = []

    def scan1(istat):
        fatti1.append(istat)
        n["i"] += 1
        if n["i"] >= 2:
            stop.write_text("stop", "utf-8")  # halt after 2 comuni
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", scan1)
    rc1 = registro_cli.cmd_bootstrap(_args(cat, limit=5, checkpoint=cp))
    assert rc1 == registro_cli.BOOTSTRAP_STOP
    assert len(fatti1) == 2

    congelata = json.loads(cp.read_text("utf-8"))["selezione"]
    assert len(congelata) == 5  # frozen lotto of 5

    stop.unlink()
    fatti2: list[str] = []

    def scan2(istat):
        fatti2.append(istat)
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", scan2)
    rc2 = registro_cli.cmd_bootstrap(_args(cat, limit=5, checkpoint=cp, resume=True))
    assert rc2 == registro_cli.BOOTSTRAP_OK
    assert set(fatti2).isdisjoint(fatti1)               # never re-fetch a completed comune
    assert set(fatti1) | set(fatti2) == set(congelata)  # together finish the frozen selection
    assert len(fatti2) == 3


def test_retry_vuoti_riapre_solo_i_vuoti_e_salva_prima_del_fetch(tmp_path, monkeypatch):
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    selezione = ["000000", "000001", "000002"]
    registro_cli._bootstrap_salva_checkpoint(
        cp, avviato_il="2026-10-04T00:00:00+00:00", selezione=selezione,
        arruolati={"000000"}, vuoti={"000001"}, errori=[], totale_candidati=3,
    )
    visti = []

    def scan(istat):
        visti.append(istat)
        # La riapertura e' gia' durevole prima del primo fetch.
        assert json.loads(cp.read_text("utf-8"))["vuoti"] == []
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", scan)
    rc = registro_cli.cmd_bootstrap(_args(cat, checkpoint=cp, resume=True,
                                           retry_vuoti=True, max_per_run=1))
    assert rc == registro_cli.BOOTSTRAP_OK
    assert visti == ["000001"]
    dati = json.loads(cp.read_text("utf-8"))
    assert dati["arruolati"] == ["000000", "000001"]
    assert dati["vuoti"] == []
    assert "000002" in dati["selezione"]


def test_resume_canary_dopo_stop_usa_selezione_congelata(tmp_path, monkeypatch):
    """Blocker: on --resume the canary must finish the ORIGINAL selection.

    Once the first comuni are initialised they drop out of the candidate pool,
    so a recomputed canary would pick OTHER comuni. The frozen `selezione` in
    the checkpoint is authoritative — resume never re-runs canary()/lotto().
    """
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    stop = cp.with_suffix(".stop")

    coda_piena = sorted(p.stem for p in cat.glob("*.json"))
    attesa = registro_cli.bootstrap_sel.canary(
        registro_cli.bootstrap_sel.seleziona(cat, set(coda_piena), set()), per_piattaforma=2
    )
    assert len(attesa) == 10  # 2 x 5 platforms

    monkeypatch.setattr(registro_cli, "_comuni_da_censimento", lambda _db: coda_piena)
    monkeypatch.setattr(registro_cli, "_connettore_inizializzati", lambda: set())

    n = {"i": 0}
    fatti1: list[str] = []

    def scan1(istat):
        fatti1.append(istat)
        n["i"] += 1
        if n["i"] >= 5:
            stop.write_text("stop", "utf-8")  # halt after the first 5 of the canary
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", scan1)
    rc1 = registro_cli.cmd_bootstrap(_args(cat, canary=True, checkpoint=cp))
    assert rc1 == registro_cli.BOOTSTRAP_STOP
    assert set(fatti1) == set(attesa[:5])

    # Prod drift: the 5 done comuni are now initialised and leave the queue.
    stop.unlink()
    fatti = set(fatti1)
    monkeypatch.setattr(registro_cli, "_connettore_inizializzati", lambda: set(fatti))
    monkeypatch.setattr(
        registro_cli, "_comuni_da_censimento",
        lambda _db: [c for c in coda_piena if c not in fatti],
    )
    fatti2: list[str] = []

    def scan2(istat):
        fatti2.append(istat)
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", scan2)
    rc2 = registro_cli.cmd_bootstrap(_args(cat, canary=True, checkpoint=cp, resume=True))
    assert rc2 == registro_cli.BOOTSTRAP_OK
    # Resume finishes the ORIGINAL canary (its remaining 5), not a fresh one.
    assert set(fatti2) == set(attesa[5:])
    assert set(fatti1) | set(fatti2) == set(attesa)


def test_checkpoint_corrotto_non_esegue_fetch(tmp_path, _stub):
    """A corrupt checkpoint stops the run (exit 2) with no fetch — no silent restart."""
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    cp.write_text("{ not json", "utf-8")
    rc = registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp, resume=True))
    assert rc == 2
    assert _stub == []  # never fetched on a corrupt checkpoint


def test_checkpoint_senza_selezione_e_invalido(tmp_path, _stub):
    """Valid JSON but missing the frozen `selezione` is rejected on resume."""
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"
    cp.write_text(json.dumps({"completati": [], "errori": [], "avviato_il": "x"}), "utf-8")
    rc = registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp, resume=True))
    assert rc == 2
    assert _stub == []


def test_resume_senza_checkpoint_esistente_rifiuta(tmp_path, _stub):
    """--resume with no checkpoint on disk refuses rather than start fresh."""
    cat = _scena(tmp_path)
    cp = tmp_path / "assente.json"
    rc = registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp, resume=True))
    assert rc == 2
    assert _stub == []


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
    assert guasto not in dati1["arruolati"]  # errored -> NOT enrolled
    assert guasto not in dati1["vuoti"]
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
    assert guasto in dati2["arruolati"]  # ok on retry -> enrolled
    assert dati2["errori"] == []  # cleared on successful retry


def test_vuoto_non_arruolato_e_terminale(tmp_path, monkeypatch):
    """A `vuoto` read (no record) lands in `vuoti`, never `arruolati`.

    Semantics (option 3): vuoto is a successful read with NO data-live record.
    It must NOT count as enrolled, must stay out of the refresh, and must be
    terminal on --resume (skipped, not retried) — only `errori` are retried.
    """
    cat = _scena(tmp_path)
    cp = tmp_path / "bootstrap.json"

    def fake_coda(_db):
        return sorted(p.stem for p in cat.glob("*.json"))

    monkeypatch.setattr(registro_cli, "_comuni_da_censimento", fake_coda)
    monkeypatch.setattr(registro_cli, "_connettore_inizializzati", lambda: set())

    selezione = registro_cli.bootstrap_sel.lotto(
        registro_cli.bootstrap_sel.seleziona(cat, set(fake_coda(None)), set()), 3
    )
    svuota = selezione[0]  # this one reads empty; the other two enrol

    def fake_scan(istat):
        if istat == svuota:
            return "vuoto", f"{istat} — vuoto"
        return "ok", f"{istat} — ok"

    monkeypatch.setattr(registro_cli, "_scansiona_uno", fake_scan)
    rc = registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp))
    assert rc == registro_cli.BOOTSTRAP_OK  # a vuoto alone is not an error

    dati = json.loads(cp.read_text("utf-8"))
    assert svuota in dati["vuoti"]
    assert svuota not in dati["arruolati"]
    assert len(dati["arruolati"]) == 2
    assert dati["errori"] == []

    # Resume: the vuoto is terminal — skipped, not retried.
    fetched: list[str] = []

    def fake_scan2(istat):
        fetched.append(istat)
        return fake_scan(istat)

    monkeypatch.setattr(registro_cli, "_scansiona_uno", fake_scan2)
    rc2 = registro_cli.cmd_bootstrap(_args(cat, limit=3, checkpoint=cp, resume=True))
    assert rc2 == registro_cli.BOOTSTRAP_OK
    assert fetched == []  # nothing left to do: arruolati + vuoti cover the selection


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
    {"max_per_run": 0},
    {"max_per_run": 2},
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
