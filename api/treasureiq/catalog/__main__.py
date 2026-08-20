"""CLI for the offline shadow catalog run.

Example:
    PYTHONPATH=. python -m treasureiq.catalog \
      --mappa-json /tmp/mappa.json --output data-live/catalog-shadow \
      --measurement-id run-1
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from treasureiq.catalog.shadow_run import persist_shadow_snapshots
from treasureiq.catalog.store import SnapshotStore
from treasureiq.mappa_connettore import MappaConnettore


def main() -> int:
    parser = argparse.ArgumentParser(description="Persisti snapshot TIQ in shadow mode")
    parser.add_argument("--mappa-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--measurement-id", required=True)
    args = parser.parse_args()

    mappa = MappaConnettore.model_validate_json(args.mappa_json.read_text(encoding="utf-8"))
    measured_at = datetime.now(timezone.utc)
    events = persist_shadow_snapshots(
        mappa,
        store=SnapshotStore(args.output),
        measurement_id=args.measurement_id,
        measured_at=measured_at,
    )
    print(f"snapshot salvati: {mappa.codice_istat} ({args.measurement_id})")
    for event in events:
        print(f"drift: {event.kind.value} {event.surface} {event.changes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
