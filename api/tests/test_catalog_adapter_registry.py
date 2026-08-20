import pytest

from treasureiq.catalog import (
    AdapterRegistry,
    AccessMode,
    FreshnessPolicy,
    RequestLimits,
    Surface,
    WebScrapeAdapter,
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


def test_registry_resolves_indirect_fallback_for_unknown_platform() -> None:
    registry = AdapterRegistry()
    registry.register(WebScrapeAdapter())

    adapter = registry.resolve(
        platform_id="halley",
        surface=Surface.ORDINARY_DATA.value,
        capability="offices",
        access_mode=AccessMode.INDIRECT,
    )

    assert adapter is not None
    assert adapter.name == "web_scrape"


def test_fallback_requests_are_explicit_for_unknown_platform() -> None:
    registry = default_adapter_registry()

    requests = registry.fallback_requests_for(
        source_id="058003",
        platform_id="halley",
        request_prefix="fallback",
        freshness=FreshnessPolicy(max_age_seconds=86400),
        limits=RequestLimits(max_records=5),
        manifest_revision=1,
    )

    assert [request.capability for request in requests] == [
        "services",
        "offices",
        "contacts",
        "transparency",
    ]
    assert all(request.allowed_modes == ("indirect",) for request in requests)


def test_fallback_requests_are_empty_when_native_manifest_exists() -> None:
    registry = default_adapter_registry()

    assert registry.fallback_requests_for(
        source_id="058003",
        platform_id="wordpress_agid",
        request_prefix="fallback",
        freshness=FreshnessPolicy(max_age_seconds=86400),
        limits=RequestLimits(),
        manifest_revision=1,
    ) == ()


def test_wordpress_manifest_resolves_sweep_platform_alias() -> None:
    registry = default_adapter_registry()

    adapter = registry.resolve(
        platform_id="wp_design_comuni",
        surface=Surface.ORDINARY_DATA.value,
        capability="offices",
    )

    assert adapter is not None
    assert adapter.name == "wordpress_agid"


def test_registry_rejects_duplicate_adapter_names() -> None:
    registry = AdapterRegistry()
    registry.register(WordPressAgidAdapter())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(WordPressAgidAdapter())


def test_default_registry_contains_the_direct_and_indirect_adapters() -> None:
    registry = default_adapter_registry()

    assert registry.names() == ("wordpress_agid", "web_scrape")
