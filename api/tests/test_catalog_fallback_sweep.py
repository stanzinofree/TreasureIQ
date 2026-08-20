from pathlib import Path

from treasureiq.catalog.fallback_run import platform_from_sweep


def test_fallback_reuses_platform_classification_from_sweep(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "treasureiq.catalog.fallback_run.portale_del_comune",
        lambda db_path, codice: {"piattaforma": "wp_design_comuni"},
    )

    assert platform_from_sweep(tmp_path / "storico.db", "058003") == "wp_design_comuni"
