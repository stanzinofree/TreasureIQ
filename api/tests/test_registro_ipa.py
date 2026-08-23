from __future__ import annotations

import json

import treasureiq.registro as registro
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


def _prepare(monkeypatch, tmp_path, content: str | None):
    path = tmp_path / "comuni-istat.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(registro, "_COMUNI_ISTAT_PATH", path)
    monkeypatch.setattr(registro, "_comuni_ipa_cache", None)
    reset_registry_cache()
    return path


def test_carica_comuni_ipa_uses_registry_and_preserves_view(monkeypatch, tmp_path) -> None:
    _prepare(monkeypatch, tmp_path, json.dumps(_frame(), ensure_ascii=False))

    assert registro._carica_comuni_ipa() == {"001001": "C_A074"}
    assert registro._carica_comuni_ipa() == {"001001": "C_A074"}


def test_carica_comuni_ipa_missing_keeps_empty_view_and_logs_io(monkeypatch, tmp_path) -> None:
    _prepare(monkeypatch, tmp_path, None)
    messages: list[str] = []
    monkeypatch.setattr(registro.logger, "warning", lambda message, *args: messages.append(message % args))

    assert registro._carica_comuni_ipa() == {}

    log = "\n".join(messages)
    assert "I/O" in log
    assert "invalido" not in log


def test_carica_comuni_ipa_invalid_keeps_empty_view_and_logs_invalid(
    monkeypatch, tmp_path
) -> None:
    _prepare(monkeypatch, tmp_path, '[{"codice_istat": 1001}]')
    messages: list[str] = []
    monkeypatch.setattr(registro.logger, "warning", lambda message, *args: messages.append(message % args))

    assert registro._carica_comuni_ipa() == {}

    log = "\n".join(messages)
    assert "invalido" in log
    assert "invalid_codice_istat" in log
    assert "I/O" not in log
