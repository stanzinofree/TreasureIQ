"""Immutable filesystem store for backoffice fallback runs."""

from __future__ import annotations

import json
from pathlib import Path

from treasureiq.catalog.fallback_run import FallbackRun
from treasureiq.catalog.store import _atomic_write, _safe_component


class FallbackRunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, run: FallbackRun) -> Path:
        path = self.root / _safe_component(run.source_id) / _safe_component(run.platform_id)
        measurement = path / f"{_safe_component(run.run_id)}.json"
        content = run.model_dump_json(indent=2)
        if measurement.exists():
            if measurement.read_text(encoding="utf-8") != content:
                raise ValueError(f"fallback run già esistente con contenuto diverso: {measurement}")
            return measurement
        measurement.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(measurement, content)
        _atomic_write(path / "latest.json", content)
        return measurement

    def latest(self, *, source_id: str, platform_id: str) -> FallbackRun | None:
        path = self.root / _safe_component(source_id) / _safe_component(platform_id) / "latest.json"
        if not path.exists():
            return None
        try:
            return FallbackRun.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
