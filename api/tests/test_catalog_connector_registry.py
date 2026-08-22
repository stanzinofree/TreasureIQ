import pytest

from treasureiq.catalog import (
    ConnectorRegistry,
    DataRequest,
    FreshnessPolicy,
    Surface,
    WordPressAgidConnector,
    default_connector_registry,
)


def _request() -> DataRequest:
    return DataRequest(
        request_id="req-1",
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        capability="offices",
        freshness=FreshnessPolicy(max_age_seconds=3600),
        manifest_revision=1,
    )


def test_registry_resolves_connector_by_platform_and_request() -> None:
    registry = default_connector_registry()

    connector = registry.resolve(request=_request(), platform_id="wordpress_agid")

    assert connector is not None
    assert connector.name == "wordpress_agid"
    assert registry.names() == (
        "wordpress_agid",
        "municipium.base",
        "municipium.trasparenza",
        "comweb.base",
        "comweb.trasparenza",
        "peopleweb.base",
        "peopleweb.trasparenza",
        "web_scrape",
    )


def test_registry_uses_web_fallback_for_another_platform() -> None:
    registry = default_connector_registry()

    connector = registry.resolve(request=_request(), platform_id="halley")

    assert connector is not None
    assert connector.name == "web_scrape"


def test_registry_rejects_duplicate_connector_names() -> None:
    registry = ConnectorRegistry()
    registry.register(WordPressAgidConnector())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(WordPressAgidConnector())
