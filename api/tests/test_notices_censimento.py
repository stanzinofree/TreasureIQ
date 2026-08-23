"""Censimento coherence for the `notices` capability (Ramo 2, slice 3).

Slice 3 is hygiene, not new behaviour: the two halves of the bandi vocabulary
(the chat capability `notices` and the admin catalog section `public_notices`)
must stay distinct (D-R2-3, no rename), be reached through the centralized
constants (no stray literals), and be bridged in exactly one place.

It also pins the honesty boundary from D-R2-2: `notices` is served by the
`bandi_live` rail, NOT by the fleet projection — so the fleet must NOT advertise
a `notices` capability it would only ever answer with an empty batch.
"""

from __future__ import annotations

from datetime import datetime, timezone

from treasureiq.catalog.contracts import (
    CAPABILITY_NOTICES,
    CATALOG_SECTION_PUBLIC_NOTICES,
    CATALOG_SECTION_TO_CAPABILITY,
    Surface,
    capability_for_section,
)
from treasureiq.catalog.flotta import _projection
from treasureiq.catalog.flotta._adapter import FLOTTA_MANIFEST
from treasureiq.catalog.planner import _CAPABILITY_BY_TOPIC
from treasureiq.catalog.shadow import platform_snapshot


# --- two vocabularies, distinct on purpose (D-R2-3) ---------------------------


def test_vocabularies_stay_distinct_no_rename():
    # The chat capability and the admin section are different strings and neither
    # is renamed into the other.
    assert CAPABILITY_NOTICES == "notices"
    assert CATALOG_SECTION_PUBLIC_NOTICES == "public_notices"
    assert CAPABILITY_NOTICES != CATALOG_SECTION_PUBLIC_NOTICES


def test_bridge_maps_section_to_capability():
    assert capability_for_section(CATALOG_SECTION_PUBLIC_NOTICES) == CAPABILITY_NOTICES
    assert CATALOG_SECTION_TO_CAPABILITY == {
        CATALOG_SECTION_PUBLIC_NOTICES: CAPABILITY_NOTICES
    }


def test_bridge_returns_none_for_unknown_section():
    assert capability_for_section("offices") is None
    assert capability_for_section("services") is None


# --- planner routes bandi through the centralized constant ---------------------


def test_planner_routes_bandi_to_notices_constant():
    assert _CAPABILITY_BY_TOPIC["bandi"] == CAPABILITY_NOTICES


# --- census section carries the section constant -------------------------------


def test_shadow_at_snapshot_uses_section_constant():
    snap = platform_snapshot(
        surface=Surface.TRANSPARENCY,
        measurement_id="m-1",
        measured_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    assert CATALOG_SECTION_PUBLIC_NOTICES in snap.sections
    # the admin section is not the chat capability sneaking in under a new name
    assert CAPABILITY_NOTICES not in snap.sections


# --- honesty boundary (D-R2-2): the fleet must NOT advertise notices ----------


def test_fleet_does_not_advertise_notices():
    # notices comes from bandi_live, not from the EsitoConnettore projection;
    # advertising it here would produce a false, always-empty batch.
    advertised = {
        (item.surface, item.capability) for item in FLOTTA_MANIFEST.capabilities
    }
    assert (Surface.TRANSPARENCY, CAPABILITY_NOTICES) not in advertised


def test_fleet_projection_has_no_notices_branch():
    # The projection reads the AT index as `transparency`; `notices` is not a
    # projected capability and must stay an empty result, on purpose.
    assert _projection.records(Surface.TRANSPARENCY, CAPABILITY_NOTICES, None) == []
