from datetime import datetime, timezone

from treasureiq.catalog.service_contracts import AuthenticationMethod, ServicePortalRole
from treasureiq.catalog.service_discovery import (
    discover_service_portal_candidates,
    update_source_inventory,
)


def test_discovery_extracts_service_portals_and_ignores_unrelated_links() -> None:
    html = """
    <a href="/">Home</a>
    <a href="https://cloud.urbi.it/urbi/progs/urp/crsurlog.sto">Avvio istanze online SPID</a>
    <a href="https://example.it/agenda-smart">Prenota appuntamento</a>
    <a href="/servizi-online/newsletter">Servizi online · Newsletter</a>
    <a href="/amministrazione-trasparente">Amministrazione trasparente</a>
    <a href="/wp-admin">Area Privata</a>
    """

    found = discover_service_portal_candidates(
        base_url="https://comune.example.it/",
        html_home=html,
        discovered_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )

    assert len(found) == 2
    assert found[0].provider_hint == "urbi"
    assert found[0].role is ServicePortalRole.ONLINE_SERVICE
    assert AuthenticationMethod.SPID in found[0].authentication
    assert found[1].provider_hint == "agenda_smart"
    assert found[1].role is ServicePortalRole.APPOINTMENT


def test_inventory_is_atomic_and_preserves_known_at_facts(tmp_path) -> None:
    first = update_source_inventory(
        live_dir=tmp_path,
        source_id="058003",
        base_url="https://comune.example.it/",
        base_platform="wordpress_agid",
        base_fingerprint="one",
        transparency_url="https://comune.example.it/at",
        transparency_platform="halley_trasparenza",
        candidates=(),
    )
    second = update_source_inventory(
        live_dir=tmp_path,
        source_id="058003",
        base_url="https://comune.example.it/",
        base_platform="wordpress_agid",
        base_fingerprint="two",
        transparency_url=None,
        transparency_platform=None,
        candidates=(),
    )

    assert first.transparency_platform == "halley_trasparenza"
    assert second.transparency_platform == "halley_trasparenza"
    assert second.base_fingerprint == "two"
