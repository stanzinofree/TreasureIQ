"""Small in-memory registry for v1 source platform contracts.

This registry is deliberately not wired to runtime chat yet.  It provides a
stable lookup seam for the shadow catalog and can later be backed by the
backoffice store without changing the adapter contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.snapshots import PlatformSnapshot


@dataclass(frozen=True)
class RegisteredPlatform:
    platform_id: str
    surface: Surface
    snapshot: PlatformSnapshot


class PlatformRegistry:
    """Registry keyed by `(platform_id, surface)` with strict replacement."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, Surface], RegisteredPlatform] = {}

    def register(self, snapshot: PlatformSnapshot) -> None:
        key = (snapshot.platform_id, snapshot.surface)
        self._items[key] = RegisteredPlatform(
            platform_id=snapshot.platform_id,
            surface=snapshot.surface,
            snapshot=snapshot,
        )

    def get(self, platform_id: str, surface: Surface) -> PlatformSnapshot | None:
        item = self._items.get((platform_id, surface))
        return item.snapshot if item is not None else None

    def all(self) -> tuple[PlatformSnapshot, ...]:
        return tuple(item.snapshot for item in self._items.values())
