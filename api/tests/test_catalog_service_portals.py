from datetime import datetime, timezone

from treasureiq.catalog.service_contracts import ServicePortalCandidate, ServicePortalRole
from treasureiq.catalog.service_portals import group_service_portal_candidates


def test_sp_groups_entrypoints_by_platform_and_keeps_unknown_host_bucket() -> None:
    candidates = (
        ServicePortalCandidate(
            url="https://example.it/a", label="Area personale",
            source_url="https://example.it", provider_hint="urbi",
            platform_id="urbi", role=ServicePortalRole.PERSONAL_AREA,
            recognition_status="confirmed", discovered_at=datetime.now(timezone.utc),
        ),
        ServicePortalCandidate(
            url="https://example.it/b", label="Appuntamenti",
            source_url="https://example.it", provider_hint="urbi",
            platform_id="urbi", role=ServicePortalRole.APPOINTMENT,
            recognition_status="confirmed", discovered_at=datetime.now(timezone.utc),
        ),
        ServicePortalCandidate(
            url="https://other.it/login", label="Servizi",
            source_url="https://example.it", role=ServicePortalRole.ONLINE_SERVICE,
            discovered_at=datetime.now(timezone.utc),
        ),
    )
    groups = group_service_portal_candidates(candidates)
    assert len(groups) == 2
    urbi = next(group for group in groups if group.platform_id == "urbi")
    assert len(urbi.entrypoints) == 2
    assert len(urbi.roles) == 2
    assert any(group.platform_id is None for group in groups)
