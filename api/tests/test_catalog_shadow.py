"""Shadow translation tests: v0 map -> v1 catalog snapshots."""

from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessMode,
    PlatformRegistry,
    Surface,
    municipality_snapshots,
    platform_snapshot,
)
from treasureiq.mappa_connettore import AssetRest, AssetServizi, MappaConnettore

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _mappa(*, at: str = "REST") -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Albano Laziale",
        sito="https://www.comune.example.it",
        sondato_il=NOW.isoformat(),
        servizi=AssetServizi(esposto=True, rest_base="servizi", totale=12),
        uffici=AssetRest(esposto=True, rest_base="uffici", totale=4),
        contatti_via="scrape",
        amministrazione_trasparente_via=at,
    )


def test_shadow_builds_two_surfaces_and_keeps_at_separate() -> None:
    ordinary, transparency = municipality_snapshots(
        _mappa(), measurement_id="run-1", measured_at=NOW
    )

    assert ordinary.surface is Surface.ORDINARY_DATA
    assert ordinary.access_mode is AccessMode.DIRECT
    assert ordinary.capability_access_modes["services"] is AccessMode.DIRECT
    assert ordinary.capability_access_modes["contacts"] is AccessMode.MEDIATED
    assert transparency.surface is Surface.TRANSPARENCY
    assert transparency.access_mode is AccessMode.DIRECT
    assert transparency.capability_access_modes["public_notices"] is AccessMode.DIRECT


def test_at_without_rest_degrades_to_mediated() -> None:
    _, transparency = municipality_snapshots(
        _mappa(at="scrape"), measurement_id="run-1", measured_at=NOW
    )
    assert transparency.access_mode is AccessMode.MEDIATED


def test_registry_replaces_same_platform_surface_only() -> None:
    registry = PlatformRegistry()
    ordinary = platform_snapshot(
        surface=Surface.ORDINARY_DATA, measurement_id="run-1", measured_at=NOW
    )
    at = platform_snapshot(
        surface=Surface.TRANSPARENCY, measurement_id="run-1", measured_at=NOW
    )
    registry.register(ordinary)
    registry.register(at)

    assert len(registry.all()) == 2
    assert registry.get("wordpress_agid", Surface.TRANSPARENCY) == at
