"""Build v1 snapshots from existing v0 WordPress/AgID measurements."""

from __future__ import annotations

from datetime import datetime

from treasureiq.catalog.contracts import (
    AccessContract,
    AccessMode,
    AgidCompatibility,
    CapabilityStatus,
    ConnectorContract,
    SectionStatus,
    Surface,
)
from treasureiq.catalog.snapshots import (
    MunicipalityPlatformSnapshot,
    PlatformSnapshot,
)
from treasureiq.mappa_connettore import MappaConnettore


def _section_for_asset(*, exposed: bool, total: int) -> SectionStatus:
    if not exposed:
        return SectionStatus.ABSENT
    return SectionStatus.PRESENT if total > 0 else SectionStatus.PRESENT_EMPTY


def _capability_for_asset(exposed: bool) -> CapabilityStatus:
    return CapabilityStatus.VERIFIED if exposed else CapabilityStatus.UNSUPPORTED


def _fingerprint(mappa: MappaConnettore, surface: Surface, platform_id: str | None) -> str:
    """Stable shadow fingerprint, based only on measured v0 structure."""
    values = [
        platform_id or "unknown",
        surface.value,
        mappa.sito or "",
        str(mappa.servizi.rest_base),
        str(mappa.uffici.rest_base),
        mappa.contatti_via,
        mappa.amministrazione_trasparente_via,
        str(mappa.amministrazione_trasparente_rest_base),
    ]
    import hashlib

    return "sha256:" + hashlib.sha256("|".join(values).encode()).hexdigest()[:16]


def platform_snapshot(
    *, surface: Surface, measurement_id: str, measured_at: datetime
) -> PlatformSnapshot:
    """Return the static platform contract for the WordPress/AgID pilot."""
    if surface is Surface.ORDINARY_DATA:
        sections = {
            "services": "typed",
            "offices": "typed",
            "contacts": "semi_structured",
            "opening_hours": "free_text",
        }
        access = AccessContract(
            transport="rest",
            endpoints=("services", "offices"),
            authentication="public",
            pagination="verified",
            schema_version="wordpress-agid-v1",
        )
    else:
        sections = {
            "public_notices": "typed_or_free_text",
            "documents": "linked_documents",
            "deadlines": "free_text_or_document",
        }
        access = AccessContract(
            transport="rest_or_html",
            endpoints=("amm-trasparente", "pages"),
            authentication="public",
            pagination="verified_or_unknown",
            schema_version="wordpress-agid-v1",
        )
    return PlatformSnapshot(
        platform_id="wordpress_agid",
        surface=surface,
        vendor="wordpress-agid",
        agid_model_version="1",
        agid_compatibility=AgidCompatibility.PARTIAL,
        sections=sections,
        access_contract=access,
        connector_contract=ConnectorContract(
            adapter="wordpress_agid",
            mode=(
                AccessMode.DIRECT
                if surface is Surface.ORDINARY_DATA
                else AccessMode.MEDIATED
            ),
            version="1.0-shadow",
        ),
        fingerprint=f"sha256:wordpress-agid:{surface.value}",
        measured_at=measured_at,
        measurement_id=measurement_id,
    )


def municipality_snapshots(
    mappa: MappaConnettore,
    *,
    measurement_id: str,
    measured_at: datetime,
    platform_id: str | None = None,
    platform_at_id: str | None = None,
) -> tuple[MunicipalityPlatformSnapshot, MunicipalityPlatformSnapshot]:
    """Translate one existing v0 map into ordinary-data and AT snapshots."""
    ordinary_direct = mappa.servizi.esposto and mappa.uffici.esposto
    main_platform = platform_id or mappa.piattaforma_id or ("wordpress_agid" if mappa.sito else None)
    at_platform = platform_at_id or mappa.piattaforma_at_id
    ordinary = MunicipalityPlatformSnapshot(
        municipality_istat=mappa.codice_istat,
        surface=Surface.ORDINARY_DATA,
        platform_id=main_platform,
        base_url=mappa.sito,
        platform_compatibility=AgidCompatibility.PARTIAL,
        municipality_adoption={
            "services": _section_for_asset(
                exposed=mappa.servizi.esposto, total=mappa.servizi.totale
            ),
            "offices": _section_for_asset(
                exposed=mappa.uffici.esposto, total=mappa.uffici.totale
            ),
            "contacts": (
                SectionStatus.PRESENT
                if mappa.contatti_via == "REST"
                else SectionStatus.UNKNOWN
            ),
            "opening_hours": SectionStatus.UNKNOWN,
        },
        capabilities={
            "services": _capability_for_asset(mappa.servizi.esposto),
            "offices": _capability_for_asset(mappa.uffici.esposto),
            "contacts": (
                CapabilityStatus.VERIFIED
                if mappa.contatti_via == "REST"
                else CapabilityStatus.UNKNOWN
            ),
            "opening_hours": CapabilityStatus.UNKNOWN,
        },
        capability_access_modes={
            "services": AccessMode.DIRECT,
            "offices": AccessMode.DIRECT,
            "contacts": (
                AccessMode.DIRECT
                if mappa.contatti_via == "REST"
                else AccessMode.MEDIATED
            ),
        },
        access_mode=(AccessMode.DIRECT if ordinary_direct else AccessMode.MEDIATED),
        fingerprint=_fingerprint(mappa, Surface.ORDINARY_DATA, main_platform),
        measured_at=measured_at,
        measurement_id=measurement_id,
    )
    at_via_rest = mappa.amministrazione_trasparente_via == "REST"
    transparency = MunicipalityPlatformSnapshot(
        municipality_istat=mappa.codice_istat,
        surface=Surface.TRANSPARENCY,
        platform_id=at_platform,
        base_url=mappa.sito,
        platform_compatibility=AgidCompatibility.PARTIAL,
        municipality_adoption={
            "public_notices": (
                SectionStatus.PRESENT if at_via_rest else SectionStatus.UNKNOWN
            ),
            "documents": SectionStatus.UNKNOWN,
            "deadlines": SectionStatus.UNKNOWN,
        },
        capabilities={
            "public_notices": (
                CapabilityStatus.VERIFIED
                if at_via_rest
                else CapabilityStatus.UNKNOWN
            ),
            "documents": CapabilityStatus.UNKNOWN,
            "deadlines": CapabilityStatus.UNKNOWN,
        },
        capability_access_modes={
            "public_notices": (
                AccessMode.DIRECT if at_via_rest else AccessMode.MEDIATED
            ),
        },
        access_mode=(
            AccessMode.DIRECT if at_via_rest else AccessMode.MEDIATED
        ),
        fingerprint=_fingerprint(mappa, Surface.TRANSPARENCY, at_platform),
        measured_at=measured_at,
        measurement_id=measurement_id,
    )
    return ordinary, transparency
