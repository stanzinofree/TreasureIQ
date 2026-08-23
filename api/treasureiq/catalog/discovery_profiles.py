"""Deterministic discovery hints derived from the recognized BASE platform."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveryProfile:
    """Ordered hints, never a guarantee, for AT/SP discovery."""

    base_platform: str | None
    at_markers: tuple[str, ...] = ()
    service_markers: tuple[str, ...] = ()
    provider_markers: tuple[tuple[str, str], ...] = ()


_PROFILES: dict[str, DiscoveryProfile] = {
    "wordpress_agid": DiscoveryProfile(
        base_platform="wordpress_agid",
        at_markers=("amministrazione-trasparente", "amm_trasp", "trasparenza"),
        service_markers=("servizi online", "area personale", "istanze online"),
        provider_markers=(("urbi", "urbi"), ("municipium", "municipium")),
    ),
    "wp_design_comuni": DiscoveryProfile(
        base_platform="wp_design_comuni",
        at_markers=("amministrazione-trasparente", "trasparenza"),
        service_markers=("servizi online", "area personale", "sportello telematico"),
        provider_markers=(("urbi", "urbi"), ("filodiretto", "filodiretto")),
    ),
    "municipium": DiscoveryProfile(
        base_platform="municipium",
        at_markers=("amministrazione trasparente", "trasparenza"),
        service_markers=("servizi online", "area personale", "prenota appuntamento"),
        provider_markers=(("urbi", "urbi"), ("municipium", "municipium")),
    ),
}

_FALLBACK = DiscoveryProfile(base_platform=None)


def profile_for_base(base_platform: str | None) -> DiscoveryProfile:
    """Return specialized hints while preserving a generic fallback profile."""
    return _PROFILES.get(base_platform or "", _FALLBACK)
