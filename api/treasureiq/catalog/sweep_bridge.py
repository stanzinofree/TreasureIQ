"""Translate existing national-sweep rows into catalog v1 snapshots."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

from treasureiq.catalog.contracts import (
    AccessMode,
    AgidCompatibility,
    CapabilityStatus,
    SectionStatus,
    Surface,
)
from treasureiq.catalog.snapshots import MunicipalityPlatformSnapshot
from treasureiq.storico import apri

_UNKNOWN_PLATFORMS = {"", "ignota", "non_misurata", "non_trovata", "non_trovata"}


def _platform(value: object) -> str | None:
    text = str(value or "").strip()
    return None if text in _UNKNOWN_PLATFORMS else text


def _compatibility(value: object) -> AgidCompatibility:
    if value is None or value == "":
        return AgidCompatibility.UNKNOWN
    try:
        score = float(value)
    except (TypeError, ValueError):
        return AgidCompatibility.UNKNOWN
    if score >= 100:
        return AgidCompatibility.COMPATIBLE
    if score > 0:
        return AgidCompatibility.PARTIAL
    return AgidCompatibility.INCOMPATIBLE


def _ordinary_mode(indirizzabilita: object) -> AccessMode:
    value = str(indirizzabilita or "")
    if value == "api_uffici":
        return AccessMode.DIRECT
    if value == "solo_html":
        return AccessMode.INDIRECT
    return AccessMode.UNAVAILABLE


def _section_statuses(row: Mapping[str, object]) -> tuple[dict[str, SectionStatus], dict[str, CapabilityStatus]]:
    exposed = {
        item.strip()
        for item in str(row.get("sezioni_esposte") or "").split(",")
        if item.strip()
    }
    measured = row.get("sezioni_esposte") is not None
    section_names = ("services", "offices", "contacts", "transparency")
    sections = {
        name: SectionStatus.PRESENT if name in exposed else SectionStatus.UNKNOWN
        for name in section_names
    }
    capabilities = {
        name: CapabilityStatus.VERIFIED if name in exposed else CapabilityStatus.UNKNOWN
        for name in section_names
    }
    if not measured:
        sections = {name: SectionStatus.UNKNOWN for name in section_names}
        capabilities = {name: CapabilityStatus.UNKNOWN for name in section_names}
    return sections, capabilities


def snapshots_from_sweep_row(
    row: Mapping[str, object], *, measurement_id: str, measured_at: datetime
) -> tuple[MunicipalityPlatformSnapshot, MunicipalityPlatformSnapshot]:
    """Build ordinary and AT snapshots from a ``portale_snapshot`` row.

    Missing sweep measurements remain ``UNKNOWN``; they are never converted to
    a negative catalog assertion.
    """
    istat = str(row["codice_istat"])
    platform_id = _platform(row.get("piattaforma"))
    platform_at_id = _platform(row.get("piattaforma_at"))
    sections, capabilities = _section_statuses(row)
    ordinary_mode = _ordinary_mode(row.get("indirizzabilita"))
    base_url = row.get("url_finale") or row.get("url_dichiarato")
    ordinary = MunicipalityPlatformSnapshot(
        municipality_istat=istat,
        surface=Surface.ORDINARY_DATA,
        platform_id=platform_id,
        base_url=str(base_url) if base_url else None,
        platform_compatibility=_compatibility(row.get("aderenza")),
        municipality_adoption={
            "services": sections["services"],
            "offices": sections["offices"],
            "contacts": sections["contacts"],
            "opening_hours": SectionStatus.UNKNOWN,
        },
        capabilities={
            "services": capabilities["services"],
            "offices": capabilities["offices"],
            "contacts": capabilities["contacts"],
            "opening_hours": CapabilityStatus.UNKNOWN,
        },
        capability_access_modes={
            "services": ordinary_mode,
            "offices": ordinary_mode,
            "contacts": ordinary_mode,
        },
        access_mode=ordinary_mode,
        fingerprint=str(row.get("impronta_declinazione") or row.get("impronta_grezza") or "") or None,
        measured_at=measured_at,
        measurement_id=measurement_id,
    )
    at_mode = AccessMode.MEDIATED if platform_at_id else AccessMode.UNAVAILABLE
    transparency = MunicipalityPlatformSnapshot(
        municipality_istat=istat,
        surface=Surface.TRANSPARENCY,
        platform_id=platform_at_id,
        base_url=str(row.get("at_url")) if row.get("at_url") else None,
        platform_compatibility=_compatibility(row.get("aderenza")),
        municipality_adoption={
            "public_notices": SectionStatus.PRESENT if platform_at_id else SectionStatus.UNKNOWN,
            "documents": SectionStatus.UNKNOWN,
            "deadlines": SectionStatus.UNKNOWN,
        },
        capabilities={
            "public_notices": CapabilityStatus.VERIFIED if platform_at_id else CapabilityStatus.UNKNOWN,
            "documents": CapabilityStatus.UNKNOWN,
            "deadlines": CapabilityStatus.UNKNOWN,
        },
        capability_access_modes={"public_notices": at_mode},
        access_mode=at_mode,
        fingerprint=None,
        measured_at=measured_at,
        measurement_id=measurement_id,
    )
    return ordinary, transparency


def snapshots_from_sweep_db(
    db_path: str | Path,
    *,
    codice_istat: str,
    measurement_id: str,
    measured_at: datetime,
) -> tuple[MunicipalityPlatformSnapshot, MunicipalityPlatformSnapshot] | None:
    """Read the latest persisted sweep row and translate it to v1 snapshots."""
    path = Path(db_path)
    if not path.exists():
        return None
    with apri(path) as connection:
        row = connection.execute(
            "SELECT * FROM portale_snapshot WHERE codice_istat = "
            "? ORDER BY rilevato_il DESC LIMIT 1",
            (codice_istat,),
        ).fetchone()
    return (
        snapshots_from_sweep_row(dict(row), measurement_id=measurement_id, measured_at=measured_at)
        if row is not None
        else None
    )
