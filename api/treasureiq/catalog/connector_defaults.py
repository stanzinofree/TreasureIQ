"""Application composition root for source connectors."""

from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.wordpress_connector import WordPressAgidConnector


def default_connector_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(WordPressAgidConnector())
    return registry
