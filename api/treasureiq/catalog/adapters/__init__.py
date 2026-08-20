"""Adapters that translate legacy connector results into v1 data batches."""

from treasureiq.catalog.adapters.base import CatalogAdapter
from treasureiq.catalog.adapters.defaults import default_adapter_registry
from treasureiq.catalog.adapters.registry import AdapterRegistry
from treasureiq.catalog.adapters.wordpress_agid import WordPressAgidAdapter

__all__ = [
    "AdapterRegistry",
    "CatalogAdapter",
    "WordPressAgidAdapter",
    "default_adapter_registry",
]
