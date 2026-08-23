"""Import persisted sweep measurements into the v1 catalog store."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from treasureiq.catalog.store import SnapshotStore
from treasureiq.catalog.sweep_bridge import snapshots_from_sweep_db


def persist_sweep_snapshots(
    db_path: Path,
    *,
    store: SnapshotStore,
    codice_istat: str,
    measurement_id: str,
    measured_at: datetime,
) -> tuple[Path, ...]:
    snapshots = snapshots_from_sweep_db(
        db_path,
        codice_istat=codice_istat,
        measurement_id=measurement_id,
        measured_at=measured_at,
    )
    if snapshots is None:
        return ()
    return tuple(store.save_municipality(snapshot) for snapshot in snapshots)


def persist_sweep_snapshot_batch(
    db_path: Path,
    *,
    store: SnapshotStore,
    codici_istat: tuple[str, ...],
    measurement_id: str,
    measured_at: datetime,
) -> tuple[Path, ...]:
    """Importa un blocco già scritto dal censimento nazionale.

    Il censimento salva a blocchi per poter riprendere un run interrotto. Il
    catalogo segue la stessa granularità: un blocco completato diventa subito
    disponibile, senza aspettare la fine dello sweep.
    """
    paths: list[Path] = []
    for codice_istat in codici_istat:
        paths.extend(
            persist_sweep_snapshots(
                db_path,
                store=store,
                codice_istat=codice_istat,
                measurement_id=measurement_id,
                measured_at=measured_at,
            )
        )
    return tuple(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa una misura sweep nel catalogo v1")
    parser.add_argument("--db", type=Path, default=Path("data/storico.db"))
    parser.add_argument("--istat", required=True)
    parser.add_argument("--measurement-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    paths = persist_sweep_snapshots(
        args.db,
        store=SnapshotStore(args.output),
        codice_istat=args.istat,
        measurement_id=args.measurement_id,
        measured_at=datetime.now(timezone.utc),
    )
    if not paths:
        print(f"nessuna misura sweep per {args.istat}")
        return 1
    print(f"importati {len(paths)} snapshot per {args.istat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
