from __future__ import annotations

import json

import pytest

import treasureiq.registro_cli as registro_cli
import treasureiq.sonda_live as sonda_live
from treasureiq.municipality_registry import MunicipalityRecord, reset_registry_cache


def _frame() -> list[dict[str, str]]:
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
            "sito": "www.comune.albanolaziale.rm.it",
            "codice_ipa": "C_A132",
        },
    ]


def _path(monkeypatch, tmp_path, content: str | None):
    path = tmp_path / "comuni-istat.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(sonda_live, "COMUNI_ISTAT_PATH", path)
    reset_registry_cache()
    return path


def test_comuni_tutti_uses_registry_records(monkeypatch, tmp_path) -> None:
    path = _path(monkeypatch, tmp_path, json.dumps(_frame(), ensure_ascii=False))

    assert registro_cli._comuni_tutti() == ["001001", "058003"]
    assert registro_cli._anagrafe_comuni()["001001"].nome == "Agliè"
    assert isinstance(registro_cli._anagrafe_comuni()["001001"], MunicipalityRecord)
    assert path.exists()


def test_comuni_tutti_missing_keeps_legacy_system_exit(monkeypatch, tmp_path) -> None:
    path = _path(monkeypatch, tmp_path, None)

    with pytest.raises(SystemExit, match="make frame-nazionale") as exc:
        registro_cli._comuni_tutti()

    assert str(path) in str(exc.value)


def test_anagrafe_invalid_frame_reports_issue_codes(monkeypatch, tmp_path) -> None:
    _path(monkeypatch, tmp_path, '[{"codice_istat": 1001}]')

    with pytest.raises(SystemExit) as exc:
        registro_cli._anagrafe_comuni()

    assert "comuni-istat.json invalido" in str(exc.value)
    assert "invalid_codice_istat" in str(exc.value)
