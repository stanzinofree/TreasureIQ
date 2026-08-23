from __future__ import annotations

import json
from pathlib import Path

import treasureiq.dati_cli as dati_cli
from treasureiq.municipality_registry import reset_registry_cache


def _frame() -> list[dict[str, str | None]]:
    return [
        {
            "codice_istat": "001001",
            "nome": "Agliè",
            "provincia": "TO",
            "regione": "Piemonte",
            "sito": "www.comune.aglie.to.it",
            "codice_ipa": "C_A074",
        },
        {
            "codice_istat": "058003",
            "nome": "Albano Laziale",
            "provincia": "RM",
            "regione": "Lazio",
            "sito": None,
            "codice_ipa": None,
        },
    ]


def _prepare(monkeypatch, tmp_path: Path, content: str | None) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    if content is not None:
        (data_dir / "comuni-istat.json").write_text(content, encoding="utf-8")
    monkeypatch.setattr(dati_cli, "DATA_DIR", data_dir)
    monkeypatch.setattr(dati_cli, "load_enti", lambda: {})
    monkeypatch.setattr(dati_cli, "_voci_live", lambda: [])
    reset_registry_cache()
    return data_dir


def test_stato_uses_validated_frame_and_preserves_counts(monkeypatch, tmp_path, capsys) -> None:
    _prepare(monkeypatch, tmp_path, json.dumps(_frame(), ensure_ascii=False))

    assert dati_cli._stato(None) == 0

    output = capsys.readouterr()
    assert "FRAME NAZIONALE               : 2 comuni, 1 con sito" in output.out
    assert output.err == ""


def test_stato_omits_frame_section_when_absent(monkeypatch, tmp_path, capsys) -> None:
    _prepare(monkeypatch, tmp_path, None)

    assert dati_cli._stato(None) == 0

    output = capsys.readouterr()
    assert "FRAME NAZIONALE" not in output.out
    assert output.err == ""


def test_stato_reports_invalid_frame_without_aborting(monkeypatch, tmp_path, capsys) -> None:
    _prepare(monkeypatch, tmp_path, "[{\"codice_istat\": 1001}]")

    assert dati_cli._stato(None) == 0

    output = capsys.readouterr()
    assert "FRAME NAZIONALE" not in output.out
    assert "frame nazionale invalido" in output.err
    assert "invalid_codice_istat" in output.err
