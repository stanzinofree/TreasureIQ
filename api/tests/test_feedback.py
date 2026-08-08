"""POST /api/feedback: salva e basta (D-03), niente eco, niente GET (R-3).
Store monkeypatchato su tmp_path — i dati del container di test sono `:ro`,
quindi lo store reale in LIVE_DIR non e' mai scrivibile qui."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import treasureiq.api as api

client = TestClient(api.app)


def _reset(monkeypatch, path) -> None:
    monkeypatch.setattr(api, "FEEDBACK_PATH", path)
    monkeypatch.setattr(api, "_feedback_memory_only", False)
    monkeypatch.setattr(api, "_feedback_memory", [])


def test_feedback_happy_path_appende_una_riga(tmp_path, monkeypatch):
    feedback_path = tmp_path / "feedback.jsonl"
    _reset(monkeypatch, feedback_path)

    risposta = client.post("/api/feedback", json={"testo": "utile", "voto": 5})

    assert risposta.status_code == 200
    assert risposta.json() == {"ok": True}
    righe = feedback_path.read_text("utf-8").splitlines()
    assert len(righe) == 1
    record = json.loads(righe[0])
    assert record["testo"] == "utile"
    assert record["voto"] == 5
    assert record["ts"]


def test_feedback_secondo_post_accoda_non_sovrascrive(tmp_path, monkeypatch):
    feedback_path = tmp_path / "feedback.jsonl"
    _reset(monkeypatch, feedback_path)

    client.post("/api/feedback", json={"testo": "primo", "voto": None})
    client.post("/api/feedback", json={"testo": "secondo", "voto": 3})

    righe = feedback_path.read_text("utf-8").splitlines()
    assert len(righe) == 2


def test_feedback_voto_assente_e_null(tmp_path, monkeypatch):
    feedback_path = tmp_path / "feedback.jsonl"
    _reset(monkeypatch, feedback_path)

    risposta = client.post("/api/feedback", json={"testo": "senza voto"})

    assert risposta.status_code == 200
    record = json.loads(feedback_path.read_text("utf-8").splitlines()[0])
    assert record["voto"] is None


def test_feedback_testo_vuoto_422(tmp_path, monkeypatch):
    _reset(monkeypatch, tmp_path / "feedback.jsonl")

    risposta = client.post("/api/feedback", json={"testo": ""})

    assert risposta.status_code == 422


def test_feedback_testo_troppo_lungo_422(tmp_path, monkeypatch):
    _reset(monkeypatch, tmp_path / "feedback.jsonl")

    risposta = client.post("/api/feedback", json={"testo": "x" * 2001})

    assert risposta.status_code == 422


def test_feedback_voto_fuori_range_422(tmp_path, monkeypatch):
    _reset(monkeypatch, tmp_path / "feedback.jsonl")

    risposta = client.post("/api/feedback", json={"testo": "ok", "voto": 6})

    assert risposta.status_code == 422


def test_feedback_fallback_memoria_su_disco_non_scrivibile(tmp_path, monkeypatch):
    # Una directory al posto del file: aprirla in append fallisce con OSError,
    # esattamente come un mount read-only.
    percorso_non_scrivibile = tmp_path / "feedback.jsonl"
    percorso_non_scrivibile.mkdir()
    _reset(monkeypatch, percorso_non_scrivibile)

    risposta = client.post("/api/feedback", json={"testo": "fallback", "voto": 2})

    assert risposta.status_code == 200
    assert risposta.json() == {"ok": True}
    assert api._feedback_memory_only is True
    assert len(api._feedback_memory) == 1
    assert api._feedback_memory[0]["testo"] == "fallback"


def test_feedback_risposta_non_contiene_eco_del_testo(tmp_path, monkeypatch):
    _reset(monkeypatch, tmp_path / "feedback.jsonl")

    risposta = client.post("/api/feedback", json={"testo": "testo segreto del cittadino", "voto": 4})

    assert "testo segreto" not in risposta.text
