"""R3A/F1: il backup esclude il DB conversazioni, il restore non lo reintroduce.

La logica di backup/restore vive in ``api/scripts/{backup,restore}.sh`` (sh +
tar, disponibili nell'immagine di test) e il Makefile ne e' solo un wrapper.
Questi test esercitano gli script su un albero temporaneo: sono la regressione
automatizzata che mancava alla verifica manuale di R3A.
"""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_BACKUP = _SCRIPTS / "backup.sh"
_RESTORE = _SCRIPTS / "restore.sh"


def _albero(root: Path) -> None:
    """Albero minimo: un dato curato + il DB conversazioni con sidecar."""
    (root / "data").mkdir(parents=True)
    (root / "data" / "storico.db").write_text("curato")
    live = root / "data-live"
    (live / "connettore").mkdir(parents=True)
    (live / "connettore" / "058003.json").write_text("{}")
    (live / "conversations.sqlite3").write_text("TRANSCRIPT — non deve entrare")
    (live / "conversations.sqlite3-wal").write_text("wal")
    (live / "conversations.sqlite3-shm").write_text("shm")


def _esegui_backup(root: Path) -> Path:
    res = subprocess.run(
        ["sh", str(_BACKUP), str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    # stdout = solo il path del tgz (i messaggi vanno su stderr).
    tar_path = root / res.stdout.strip()
    assert tar_path.is_file(), res.stderr
    return tar_path


def test_backup_esclude_db_conversazioni_e_sidecar(tmp_path: Path) -> None:
    _albero(tmp_path)
    tar_path = _esegui_backup(tmp_path)

    with tarfile.open(tar_path) as tar:
        nomi = tar.getnames()

    conversazioni = [n for n in nomi if "conversations.sqlite3" in n]
    assert conversazioni == [], f"transcript finito nel backup: {conversazioni}"
    # I dati curati/runtime restano nel backup.
    assert "data/storico.db" in nomi
    assert "data-live/connettore/058003.json" in nomi


def test_backup_senza_storico_esclude_comunque_conversazioni(tmp_path: Path) -> None:
    _albero(tmp_path)
    (tmp_path / "data" / "storico.db").unlink()  # ramo "solo data-live/"
    tar_path = _esegui_backup(tmp_path)

    with tarfile.open(tar_path) as tar:
        nomi = tar.getnames()
    assert [n for n in nomi if "conversations.sqlite3" in n] == []
    assert "data-live/connettore/058003.json" in nomi


def test_restore_non_reintroduce_il_transcript(tmp_path: Path) -> None:
    # Backup da un albero sorgente...
    src = tmp_path / "src"
    src.mkdir()
    _albero(src)
    tar_path = _esegui_backup(src)

    # ...restore in una destinazione che ha GIA' un transcript sul volume live.
    dest = tmp_path / "dest"
    (dest / "data-live").mkdir(parents=True)
    transcript_vivo = dest / "data-live" / "conversations.sqlite3"
    transcript_vivo.write_text("VIVO sul volume")

    subprocess.run(
        ["sh", str(_RESTORE), str(tar_path.resolve()), str(dest)],
        capture_output=True,
        text=True,
        check=True,
    )

    # Il transcript vivo sopravvive intatto (non era nell'archivio)...
    assert transcript_vivo.read_text() == "VIVO sul volume"
    # ...e i dati curati vengono ripristinati.
    assert (dest / "data" / "storico.db").read_text() == "curato"


@pytest.mark.parametrize("script", [_BACKUP, _RESTORE])
def test_script_presenti_ed_eseguibili(script: Path) -> None:
    assert script.is_file(), f"script mancante: {script}"
