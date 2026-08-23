"""Shadow-run orchestration for v0 connector maps."""

from __future__ import annotations

from datetime import datetime

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.drift import DriftEvent, compare_snapshots
from treasureiq.catalog.shadow import municipality_snapshots, platform_snapshot
from treasureiq.catalog.snapshots import PlatformSnapshot
from treasureiq.catalog.store import SnapshotStore
from treasureiq.mappa_connettore import MappaConnettore


def persist_shadow_snapshots(
    mappa: MappaConnettore,
    *,
    store: SnapshotStore,
    measurement_id: str,
    measured_at: datetime,
) -> tuple[DriftEvent, ...]:
    """Persist one v0 map as v1 snapshots and return pre-write drift events."""
    platform_snapshots = (
        platform_snapshot(
            surface=Surface.ORDINARY_DATA,
            measurement_id=measurement_id,
            measured_at=measured_at,
        ),
        platform_snapshot(
            surface=Surface.TRANSPARENCY,
            measurement_id=measurement_id,
            measured_at=measured_at,
        ),
    )
    municipality = municipality_snapshots(
        mappa, measurement_id=measurement_id, measured_at=measured_at
    )

    events: list[DriftEvent] = []
    for current in (*platform_snapshots, *municipality):
        previous = (
            store.latest_platform(current.platform_id, current.surface)
            if isinstance(current, PlatformSnapshot)
            else store.latest_municipality(current.municipality_istat, current.surface)
        )
        if previous is not None:
            events.append(compare_snapshots(previous, current))

    for current in platform_snapshots:
        store.save_platform(current)
    for current in municipality:
        store.save_municipality(current)
    return tuple(events)
