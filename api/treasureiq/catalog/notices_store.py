"""Persistenza del produttore nazionale per gli avvisi live.

Il produttore salva lo snapshot canonico, non le opportunita' estratte: titoli,
link e scadenze restano citabili e la classificazione conversazionale resta a
valle. Anche un esito vuoto o non coperto viene salvato, cosi' un worker non
ritenta lo stesso comune ad ogni esecuzione.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from treasureiq.bandi_live import bandi_arricchiti
from treasureiq.catalog.contracts import FreshnessStatus
from treasureiq.catalog.freshness import freshness
from treasureiq.catalog.notices import NoticeSnapshot, snapshot_da_bandi_live
from treasureiq.catalog.store import _atomic_write, _safe_component


class NoticeStore:
    """Latest canonical notice snapshot per comune, written atomically."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, source_id: str) -> Path:
        return self.root / f"{_safe_component(source_id)}.json"

    def save(self, snapshot: NoticeSnapshot) -> Path:
        path = self.path_for(snapshot.source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, snapshot.model_dump_json(indent=1))
        return path

    def load(self, source_id: str, *, max_age_seconds: int | None = None) -> NoticeSnapshot | None:
        path = self.path_for(source_id)
        if not path.exists():
            return None
        try:
            snapshot = NoticeSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if max_age_seconds is not None:
            state = freshness(snapshot.retrieved_at, max_age_seconds).status
            if state is not FreshnessStatus.FRESH:
                return None
        return snapshot


def produce(codice_istat: str, *, store: NoticeStore) -> NoticeSnapshot:
    """Read one comune without LLM enrichment and persist its canonical notices."""
    snapshot = snapshot_da_bandi_live(
        bandi_arricchiti(codice_istat, usa_cache=False, estrai_requisiti=False)
    )
    store.save(snapshot)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produci uno snapshot nazionale avvisi")
    parser.add_argument("--istat", required=True)
    parser.add_argument("--output", type=Path, default=Path("data-live/notices"))
    args = parser.parse_args(argv)

    snapshot = produce(
        args.istat,
        store=NoticeStore(args.output),
    )
    print(json.dumps({
        "istat": snapshot.source_id,
        "coverage": snapshot.coverage_status,
        "notices": len(snapshot.notices),
        "retrieved_at": snapshot.retrieved_at,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
