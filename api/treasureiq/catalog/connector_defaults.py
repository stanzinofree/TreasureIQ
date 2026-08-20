"""Application composition root for source connectors."""

from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.wordpress_connector import WordPressAgidConnector
from treasureiq.catalog.web_connector import WebScrapeConnector


def default_connector_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(WordPressAgidConnector())
    registry.register(WebScrapeConnector())
    return registry
