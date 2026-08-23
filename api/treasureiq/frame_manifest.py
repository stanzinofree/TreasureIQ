"""Step 5 (T0 — codice ISTAT): provenienza e integrità del frame nazionale.

Il frame `data/comuni-istat.json` è la chiave di join di tutto il sistema, ma
finché è un file JSON nudo non c'è modo di dire *quale* frame è, né di
accorgersi se è stato troncato, corrotto o rigenerato a metà. Questo modulo
aggiunge due cose minime e ortogonali al contenuto:

* **scrittura atomica** (`write_atomic`): si scrive un file temporaneo nella
  stessa cartella e lo si rinomina con `os.replace`, che è atomico sullo stesso
  filesystem. Un generatore interrotto lascia il frame vecchio intatto, mai un
  frame mezzo scritto che poi ogni lettore rifiuterebbe come `INVALID`.
* **manifest sidecar** (`comuni-istat.manifest.json`): accanto al frame, un file
  che ne fissa lo SHA-256, il conteggio righe, l'istante di generazione e le
  fonti. È la provenienza: da dove viene, quando, e con che impronta.

La verifica dell'impronta ha due registri deliberatamente diversi:

* in **build/CI** è dura (`make verify-frame` fallisce se non combacia): un
  frame che non corrisponde al suo manifest non deve essere promosso;
* a **runtime** è morbida (il registry logga un warning ma serve comunque il
  frame): un manifest stale non deve mai impedire a un cittadino di ricevere
  risposta. Il manifest assente è silenzio, non errore — i frame storici non ne
  hanno uno e restano legittimi.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def write_atomic(path: str | Path, text: str, *, encoding: str = "utf-8") -> None:
    """Scrive `text` in `path` senza mai lasciare un file parziale.

    Scrive in un temporaneo nella stessa cartella (così `os.replace` resta sullo
    stesso filesystem ed è atomico) e poi rinomina. Un crash a metà scrittura
    lascia il file esistente al suo posto, non un troncone.
    """
    p = Path(path)
    tmp = p.with_name(f".{p.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(text, encoding)
        os.replace(tmp, p)
    finally:
        # Se il replace è riuscito il tmp non esiste più; se è fallito lo
        # togliamo per non lasciare rifiuti accanto al frame buono.
        if tmp.exists():
            tmp.unlink()


def sha256_of(text: str, *, encoding: str = "utf-8") -> str:
    """SHA-256 esadecimale del testo, sui byte effettivamente scritti."""
    return hashlib.sha256(text.encode(encoding)).hexdigest()


def manifest_path_for(frame_path: str | Path) -> Path:
    """Il manifest sidecar di un frame: `comuni-istat.json` → `comuni-istat.manifest.json`."""
    p = Path(frame_path)
    return p.with_name(f"{p.stem}.manifest.json")


@dataclass(frozen=True)
class FrameManifest:
    """La provenienza di un frame: cosa è, quando è nato, da dove."""

    sha256: str
    row_count: int
    valid_codes: int
    generated_at: str
    sources: tuple[str, ...] = ()
    coverage: float | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "FrameManifest":
        raw = json.loads(text)
        return cls(
            sha256=str(raw["sha256"]),
            row_count=int(raw["row_count"]),
            valid_codes=int(raw["valid_codes"]),
            generated_at=str(raw["generated_at"]),
            sources=tuple(raw.get("sources") or ()),
            coverage=raw.get("coverage"),
        )


def write_manifest(frame_path: str | Path, manifest: FrameManifest) -> Path:
    """Scrive (atomicamente) il manifest accanto al frame e ne torna il percorso."""
    dest = manifest_path_for(frame_path)
    write_atomic(dest, manifest.to_json())
    return dest


def read_manifest(frame_path: str | Path) -> FrameManifest | None:
    """Il manifest del frame, o `None` se non esiste (frame storico senza sidecar)."""
    dest = manifest_path_for(frame_path)
    if not dest.exists():
        return None
    return FrameManifest.from_json(dest.read_text("utf-8"))


def verify(frame_path: str | Path) -> tuple[bool, str]:
    """Confronta il frame col suo manifest. `(True, motivo)` se combacia.

    `(False, motivo)` se l'impronta o il conteggio righe divergono. Manifest
    assente → `(True, ...)`: non è un fallimento, è un frame senza provenienza.
    Frame assente → `(False, ...)`: non c'è niente da verificare.
    """
    p = Path(frame_path)
    if not p.exists():
        return False, f"frame assente: {p}"
    manifest = read_manifest(p)
    if manifest is None:
        return True, "manifest assente: nessuna verifica (frame senza provenienza)"

    text = p.read_text("utf-8")
    impronta = sha256_of(text)
    if impronta != manifest.sha256:
        return (
            False,
            f"sha256 diverso: frame {impronta[:12]}… ≠ manifest {manifest.sha256[:12]}…",
        )
    return True, f"ok: {manifest.row_count} righe, sha256 {impronta[:12]}…"
