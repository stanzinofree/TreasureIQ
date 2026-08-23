from __future__ import annotations

import json

import pytest

import treasureiq.ingest.censimento as censimento
import treasureiq.integration as integration
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
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "comuni-istat.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(integration, "DATA_DIR", data_dir)
    reset_registry_cache()
    return path


def test_frame_records_are_typed_and_anagrafe_projects_at_boundary(monkeypatch, tmp_path) -> None:
    _path(monkeypatch, tmp_path, json.dumps(_frame(), ensure_ascii=False))

    records = censimento._frame_records()
    assert all(isinstance(record, MunicipalityRecord) for record in records)
    anagrafe = censimento._anagrafe()
    assert anagrafe["001001"]["provincia"] == "TO"
    assert anagrafe["001001"]["sito"] == "www.comune.aglie.to.it"


def test_frame_records_missing_is_batch_system_exit(monkeypatch, tmp_path) -> None:
    path = _path(monkeypatch, tmp_path, None)

    with pytest.raises(SystemExit, match="make frame-nazionale") as exc:
        censimento._frame_records()

    assert str(path) in str(exc.value)


def test_frame_records_invalid_reports_issue_codes(monkeypatch, tmp_path) -> None:
    _path(monkeypatch, tmp_path, '[{"codice_istat": 1001}]')

    with pytest.raises(SystemExit) as exc:
        censimento._frame_records()

    assert "comuni-istat.json invalido" in str(exc.value)
    assert "invalid_codice_istat" in str(exc.value)
