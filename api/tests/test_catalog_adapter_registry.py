import pytest

from treasureiq.catalog import (
    AdapterRegistry,
    FreshnessPolicy,
    RequestLimits,
    Surface,
    WordPressAgidAdapter,
    default_adapter_registry,
)


def test_registry_resolves_wordpress_adapter_by_platform_and_surface() -> None:
    registry = AdapterRegistry()
    registry.register(WordPressAgidAdapter())

    adapter = registry.resolve(
        platform_id="wordpress_agid",
        surface=Surface.TRANSPARENCY.value,
    )

    assert adapter is not None
    assert adapter.name == "wordpress_agid"
    assert registry.names() == ("wordpress_agid",)


def test_manifest_resolves_capability_and_builds_requests() -> None:
    registry = default_adapter_registry()

    adapter = registry.resolve(
        platform_id="wordpress_agid",
        surface=Surface.ORDINARY_DATA.value,
        capability="contacts",
    )
    requests = registry.requests_for(
        source_id="058003",
        platform_id="wordpress_agid",
        request_prefix="chat",
        freshness=FreshnessPolicy(max_age_seconds=86400),
        limits=RequestLimits(max_records=25),
        manifest_revision=2,
    )

    assert adapter is not None
    assert adapter.manifest.contract_version == "catalog.v1"
    assert [request.capability for request in requests] == [
        "services",
        "offices",
        "contacts",
        "transparency",
    ]
    assert requests[2].request_id == "chat:058003:ordinary_data:contacts"
    assert requests[2].limits.max_records == 25


def test_registry_returns_none_for_unknown_platform() -> None:
    registry = AdapterRegistry()
    registry.register(WordPressAgidAdapter())

    assert registry.resolve(platform_id="halley", surface=Surface.ORDINARY_DATA.value) is None


def test_registry_rejects_duplicate_adapter_names() -> None:
    registry = AdapterRegistry()
    registry.register(WordPressAgidAdapter())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(WordPressAgidAdapter())


def test_default_registry_contains_only_the_currently_implemented_adapter() -> None:
    registry = default_adapter_registry()

    assert registry.names() == ("wordpress_agid",)
