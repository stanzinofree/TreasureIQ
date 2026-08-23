"""Step 5 (T0): scrittura atomica, manifest di provenienza, verifica integrità."""

from __future__ import annotations

from pathlib import Path

from treasureiq import frame_manifest


def test_write_atomic_sostituisce_senza_lasciare_tmp(tmp_path: Path) -> None:
    out = tmp_path / "frame.json"
    out.write_text("vecchio", "utf-8")
    frame_manifest.write_atomic(out, "nuovo")
    assert out.read_text("utf-8") == "nuovo"
    # nessun temporaneo abbandonato accanto al file buono
    assert list(tmp_path.glob(".frame.json.tmp*")) == []


def test_manifest_path_affianca_il_frame(tmp_path: Path) -> None:
    frame = tmp_path / "comuni-istat.json"
    assert frame_manifest.manifest_path_for(frame).name == "comuni-istat.manifest.json"


def test_manifest_round_trip(tmp_path: Path) -> None:
    frame = tmp_path / "comuni-istat.json"
    frame.write_text("[]\n", "utf-8")
    m = frame_manifest.FrameManifest(
        sha256="abc", row_count=3, valid_codes=3, generated_at="2026-01-01T00:00:00Z",
        sources=("u1", "u2"), coverage=0.99,
    )
    frame_manifest.write_manifest(frame, m)
    letto = frame_manifest.read_manifest(frame)
    assert letto == m


def test_read_manifest_assente_e_none(tmp_path: Path) -> None:
    frame = tmp_path / "comuni-istat.json"
    frame.write_text("[]\n", "utf-8")
    assert frame_manifest.read_manifest(frame) is None


def test_verify_ok_dopo_scrittura_coerente(tmp_path: Path) -> None:
    frame = tmp_path / "comuni-istat.json"
    testo = '[{"codice_istat":"001001"}]\n'
    frame_manifest.write_atomic(frame, testo)
    frame_manifest.write_manifest(
        frame,
        frame_manifest.FrameManifest(
            sha256=frame_manifest.sha256_of(testo),
            row_count=1, valid_codes=1, generated_at="2026-01-01T00:00:00Z",
        ),
    )
    ok, _ = frame_manifest.verify(frame)
    assert ok is True


def test_verify_rileva_manomissione(tmp_path: Path) -> None:
    frame = tmp_path / "comuni-istat.json"
    testo = '[{"codice_istat":"001001"}]\n'
    frame_manifest.write_atomic(frame, testo)
    frame_manifest.write_manifest(
        frame,
        frame_manifest.FrameManifest(
            sha256=frame_manifest.sha256_of(testo),
            row_count=1, valid_codes=1, generated_at="2026-01-01T00:00:00Z",
        ),
    )
    frame.write_text(testo.replace("001001", "999999"), "utf-8")  # manomesso
    ok, motivo = frame_manifest.verify(frame)
    assert ok is False and "sha256" in motivo


def test_verify_manifest_assente_non_fallisce(tmp_path: Path) -> None:
    frame = tmp_path / "comuni-istat.json"
    frame.write_text("[]\n", "utf-8")
    ok, motivo = frame_manifest.verify(frame)
    assert ok is True and "assente" in motivo


def test_verify_frame_assente_fallisce(tmp_path: Path) -> None:
    ok, _ = frame_manifest.verify(tmp_path / "manca.json")
    assert ok is False
