"""Application composition root for catalog adapters."""

from treasureiq.catalog.adapters.registry import AdapterRegistry
from treasureiq.catalog.adapters.web_scrape import WebScrapeAdapter
from treasureiq.catalog.adapters.wordpress_agid import WordPressAgidAdapter
from treasureiq.catalog.flotta import flotta_adapter


def default_adapter_registry() -> AdapterRegistry:
    """Build the registry used by the runtime composition root."""
    registry = AdapterRegistry()
    registry.register(WordPressAgidAdapter())
    # Single gate adapter for the fleet, before the wildcard scrape fallback so
    # the runtime resolves a native adapter for fleet platforms.
    registry.register(flotta_adapter())
    registry.register(WebScrapeAdapter())
    return registry
