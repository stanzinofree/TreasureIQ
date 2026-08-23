"""Filesystem persistence for shadow catalog snapshots.

Snapshots are immutable measurement artifacts.  The store never overwrites a
measurement; it only updates a small latest pointer after the immutable file
has been written successfully.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.snapshots import (
    MunicipalityPlatformSnapshot,
    PlatformSnapshot,
)

SnapshotT = TypeVar("SnapshotT", PlatformSnapshot, MunicipalityPlatformSnapshot)


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save_platform(self, snapshot: PlatformSnapshot) -> Path:
        path = self._measurement_path(
            "platform", snapshot.platform_id, snapshot.surface, snapshot.measurement_id
        )
        return self._save(snapshot, path)

    def save_municipality(self, snapshot: MunicipalityPlatformSnapshot) -> Path:
        path = self._measurement_path(
            "municipality",
            snapshot.municipality_istat,
            snapshot.surface,
            snapshot.measurement_id,
        )
        return self._save(snapshot, path)

    def latest_platform(self, platform_id: str, surface: Surface) -> PlatformSnapshot | None:
        return self._latest(
            "platform", platform_id, surface, PlatformSnapshot
        )

    def latest_municipality(
        self, municipality_istat: str, surface: Surface
    ) -> MunicipalityPlatformSnapshot | None:
        return self._latest(
            "municipality", municipality_istat, surface, MunicipalityPlatformSnapshot
        )

    def _measurement_path(
        self, kind: str, subject: str, surface: Surface, measurement_id: str
    ) -> Path:
        safe_subject = _safe_component(subject)
        safe_measurement = _safe_component(measurement_id)
        return (
            self.root
            / kind
            / safe_subject
            / surface.value
            / f"{safe_measurement}.json"
        )

    def _latest_path(self, kind: str, subject: str, surface: Surface) -> Path:
        return self._measurement_path(kind, subject, surface, "latest").with_name(
            "latest.json"
        )

    def _save(self, snapshot: SnapshotT, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.name == "latest.json" and path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing != snapshot.model_dump_json(indent=1):
                raise ValueError(f"snapshot già esistente con contenuto diverso: {path}")
            return path
        _atomic_write(path, snapshot.model_dump_json(indent=1))
        latest = self._latest_path(
            "platform" if isinstance(snapshot, PlatformSnapshot) else "municipality",
            snapshot.platform_id
            if isinstance(snapshot, PlatformSnapshot)
            else snapshot.municipality_istat,
            snapshot.surface,
        )
        _atomic_write(latest, snapshot.model_dump_json(indent=1))
        return path

    def _latest(
        self, kind: str, subject: str, surface: Surface, model: type[SnapshotT]
    ) -> SnapshotT | None:
        path = self._latest_path(kind, subject, surface)
        if not path.exists():
            return None
        try:
            return model.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None


def _safe_component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("componente percorso non valido")
    return value


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
