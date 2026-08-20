"""Application composition root for catalog adapters."""

from treasureiq.catalog.adapters.registry import AdapterRegistry
from treasureiq.catalog.adapters.wordpress_agid import WordPressAgidAdapter


def default_adapter_registry() -> AdapterRegistry:
    """Build the registry used by the runtime composition root."""
    registry = AdapterRegistry()
    registry.register(WordPressAgidAdapter())
    return registry
