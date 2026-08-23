"""Fase 2 slice 2A — sweep sicuro (invariante I4).

`--dry-run` esercita lo sweep end-to-end (fetch + riconoscimento) senza mai
mutare `data-live`: nessun inventario, nessun check envelope scritto, e il
refresh (che scrive lo storico via path legacy) viene rifiutato invece che
simulato. Questi test fissano quel contratto.
"""
from datetime import datetime, timezone

from treasureiq import sweep_worker
from treasureiq.catalog import confirmation, inventory_discovery, service_discovery
from treasureiq.catalog.checks import CheckResult, CheckStatus
from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.service_contracts import SourceInventory


def _stub_home(monkeypatch, html: str, at_url=None):
    monkeypatch.setattr(
        inventory_discovery, "fetch_guardato",
        lambda *a, **k: ({}, html.encode("utf-8"), "https://comune.test/"),
    )
    monkeypatch.setattr(
        inventory_discovery, "scopri_pagina_at",
        lambda **k: type("At", (), {
            "at_url": at_url,
            "piattaforma_at": type("P", (), {"value": "non_trovata"})(),
        })(),
    )


def test_discover_source_inventory_dry_run_non_scrive(tmp_path, monkeypatch):
    _stub_home(monkeypatch, "<html><body>Comune di Test</body></html>")
    result = inventory_discovery.discover_source_inventory(
        live_dir=tmp_path, source_id="000001",
        base_url="https://comune.test/", dry_run=True,
    )
    # Calcola l'inventario ma non tocca il disco.
    assert result is not None
    assert result.source_id == "000001"
    assert not list(tmp_path.rglob("*.json"))


def test_discover_source_inventory_scrive_senza_dry_run(tmp_path, monkeypatch):
    # Controprova: senza dry_run l'inventario finisce su disco (stesso setup).
    _stub_home(monkeypatch, "<html><body>Comune di Test</body></html>")
    inventory_discovery.discover_source_inventory(
        live_dir=tmp_path, source_id="000001",
        base_url="https://comune.test/", dry_run=False,
    )
    assert list(tmp_path.rglob("*.json"))


def test_update_source_inventory_dry_run_non_scrive(tmp_path):
    result = service_discovery.update_source_inventory(
        live_dir=tmp_path, source_id="000002",
        base_url="https://comune.test/", base_platform=None,
        base_fingerprint=None, transparency_url=None,
        transparency_platform=None, candidates=(),
        confirmed_at=datetime.now(timezone.utc), dry_run=True,
    )
    assert result.source_id == "000002"
    assert not list(tmp_path.rglob("*.json"))


def test_confirm_inventory_dry_run_non_scrive_check(tmp_path, monkeypatch):
    inventory = SourceInventory(
        source_id="058003",
        base_url="https://comune.test/",
        transparency_url="https://comune.test/amministrazione-trasparente",
        transparency_platform="wordpress_agid",
        updated_at=datetime.now(timezone.utc),
    )
    inventory_dir = tmp_path / "inventario"
    inventory_dir.mkdir(parents=True)
    (inventory_dir / "058003.json").write_text(
        inventory.model_dump_json(), encoding="utf-8",
    )

    def _fake_confirm_one(**kwargs):
        return CheckResult(
            source_id="058003", surface=Surface.TRANSPARENCY,
            status=CheckStatus.OK, source_health=True,
            checked_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(confirmation, "_confirm_one", _fake_confirm_one)

    results = confirmation.confirm_inventory(
        live_dir=tmp_path, source_id="058003", dry_run=True,
    )
    # Valuta l'entrypoint (ritorna il risultato) ma non scrive il check.
    assert len(results) == 1
    assert results[0].status is CheckStatus.OK
    assert not list((tmp_path / "check").rglob("*.json"))


def test_config_from_env_legge_dry_run(monkeypatch):
    monkeypatch.setenv("TREASUREIQ_SWEEP_DRY_RUN", "1")
    config = sweep_worker.config_from_env()
    assert config.dry_run is True


def test_run_batch_refresh_dry_run_rifiuta_e_non_chiama_sweep_main(monkeypatch):
    chiamato = {"sweep_main": False}
    monkeypatch.setattr(
        sweep_worker, "sweep_main",
        lambda argv: chiamato.__setitem__("sweep_main", True) or 0,
    )
    config = sweep_worker.WorkerConfig(
        db=None, mode="refresh", dry_run=True,
    )
    rc = sweep_worker.run_batch(config, ["058003"])
    # Refresh sotto dry-run: rifiutato, zero mutazioni, sweep_main mai invocato.
    # Exit code dedicato: SKIPPED, non 0 — il chiamante distingue rifiuto da
    # esecuzione riuscita.
    assert rc == sweep_worker.EXIT_REFRESH_SKIPPED
    assert chiamato["sweep_main"] is False
