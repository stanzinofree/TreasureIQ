"""Immutable v1 snapshots produced by backoffice measurements."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from treasureiq.catalog.contracts import (
    AccessContract,
    AccessMode,
    AgidCompatibility,
    CapabilityStatus,
    ConnectorContract,
    SectionStatus,
    Surface,
)


class _SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlatformSnapshot(_SnapshotModel):
    platform_id: str = Field(min_length=1)
    surface: Surface
    vendor: str | None = None
    agid_model_version: str | None = None
    agid_compatibility: AgidCompatibility
    sections: dict[str, str] = {}
    access_contract: AccessContract
    connector_contract: ConnectorContract | None = None
    fingerprint: str = Field(min_length=1)
    measured_at: datetime
    measurement_id: str = Field(min_length=1)


class MunicipalityPlatformSnapshot(_SnapshotModel):
    municipality_istat: str = Field(min_length=1, max_length=6)
    surface: Surface
    platform_id: str | None = None
    base_url: str | None = None
    platform_compatibility: AgidCompatibility
    municipality_adoption: dict[str, SectionStatus] = {}
    capabilities: dict[str, CapabilityStatus] = {}
    capability_access_modes: dict[str, AccessMode] = {}
    access_mode: AccessMode
    fingerprint: str | None = None
    measured_at: datetime
    measurement_id: str = Field(min_length=1)
