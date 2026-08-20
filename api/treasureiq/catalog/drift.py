"""Pure drift detection between consecutive catalog snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from treasureiq.catalog.snapshots import (
    MunicipalityPlatformSnapshot,
    PlatformSnapshot,
)


class DriftKind(str, Enum):
    UNCHANGED = "unchanged"
    PLATFORM_CHANGED = "platform_changed"
    SCHEMA_CHANGED = "schema_changed"
    ENDPOINT_CHANGED = "endpoint_changed"
    CAPABILITY_CHANGED = "capability_changed"
    CONNECTOR_DEGRADED = "connector_degraded"
    CONNECTOR_RECOVERED = "connector_recovered"


@dataclass(frozen=True)
class DriftEvent:
    kind: DriftKind
    subject: str
    surface: str
    previous_measurement_id: str
    current_measurement_id: str
    changes: tuple[str, ...] = ()


def compare_snapshots(
    previous: PlatformSnapshot | MunicipalityPlatformSnapshot,
    current: PlatformSnapshot | MunicipalityPlatformSnapshot,
) -> DriftEvent:
    """Compare compatible snapshots and classify the first-order change."""
    if type(previous) is not type(current):
        raise TypeError("snapshot di tipo diverso")
    if previous.surface is not current.surface:
        raise ValueError("superficie diversa")

    changes: list[str] = []
    kind = DriftKind.UNCHANGED
    if isinstance(previous, PlatformSnapshot) and isinstance(current, PlatformSnapshot):
        if previous.platform_id != current.platform_id:
            changes.append("platform_id")
            kind = DriftKind.PLATFORM_CHANGED
        if previous.agid_model_version != current.agid_model_version:
            changes.append("agid_model_version")
            kind = _prefer(kind, DriftKind.SCHEMA_CHANGED)
        if previous.access_contract.schema_version != current.access_contract.schema_version:
            changes.append("schema_version")
            kind = _prefer(kind, DriftKind.SCHEMA_CHANGED)
        if previous.access_contract.endpoints != current.access_contract.endpoints:
            changes.append("endpoints")
            kind = _prefer(kind, DriftKind.ENDPOINT_CHANGED)
        if previous.sections != current.sections:
            changes.append("sections")
            kind = _prefer(kind, DriftKind.CAPABILITY_CHANGED)
        previous_mode = (
            previous.connector_contract.mode
            if previous.connector_contract is not None
            else None
        )
        current_mode = (
            current.connector_contract.mode
            if current.connector_contract is not None
            else None
        )
        if previous_mode != current_mode:
            changes.append("connector_mode")
            if previous_mode is not None and current_mode is not None:
                kind = _prefer(
                    kind,
                    _access_mode_drift(previous_mode.value, current_mode.value),
                )
    elif isinstance(previous, MunicipalityPlatformSnapshot) and isinstance(
        current, MunicipalityPlatformSnapshot
    ):
        if previous.platform_id != current.platform_id:
            changes.append("platform_id")
            kind = DriftKind.PLATFORM_CHANGED
        if previous.base_url != current.base_url:
            changes.append("base_url")
            kind = _prefer(kind, DriftKind.ENDPOINT_CHANGED)
        if previous.capabilities != current.capabilities:
            changes.append("capabilities")
            kind = _prefer(kind, DriftKind.CAPABILITY_CHANGED)
        if previous.capability_access_modes != current.capability_access_modes:
            changes.append("capability_access_modes")
            kind = _prefer(kind, DriftKind.CAPABILITY_CHANGED)
        if previous.municipality_adoption != current.municipality_adoption:
            changes.append("municipality_adoption")
            kind = _prefer(kind, DriftKind.CAPABILITY_CHANGED)
        if previous.access_mode != current.access_mode:
            changes.append("access_mode")
            kind = _prefer(kind, _access_mode_drift(previous.access_mode.value, current.access_mode.value))

    if previous.fingerprint != current.fingerprint and "fingerprint" not in changes:
        changes.append("fingerprint")
        if kind is DriftKind.UNCHANGED:
            kind = DriftKind.PLATFORM_CHANGED

    subject = (
        previous.platform_id
        if isinstance(previous, PlatformSnapshot)
        else previous.municipality_istat
    )
    return DriftEvent(
        kind=kind,
        subject=subject,
        surface=previous.surface.value,
        previous_measurement_id=previous.measurement_id,
        current_measurement_id=current.measurement_id,
        changes=tuple(changes),
    )


_PRIORITY = {
    DriftKind.UNCHANGED: 0,
    DriftKind.CONNECTOR_RECOVERED: 1,
    DriftKind.CONNECTOR_DEGRADED: 2,
    DriftKind.CAPABILITY_CHANGED: 3,
    DriftKind.ENDPOINT_CHANGED: 4,
    DriftKind.SCHEMA_CHANGED: 5,
    DriftKind.PLATFORM_CHANGED: 6,
}


def _prefer(current: DriftKind, candidate: DriftKind) -> DriftKind:
    return candidate if _PRIORITY[candidate] > _PRIORITY[current] else current


def _access_mode_drift(previous: str, current: str) -> DriftKind:
    if previous == "direct" and current != "direct":
        return DriftKind.CONNECTOR_DEGRADED
    if previous != "direct" and current == "direct":
        return DriftKind.CONNECTOR_RECOVERED
    return DriftKind.CAPABILITY_CHANGED
