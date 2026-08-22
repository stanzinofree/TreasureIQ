"""Application composition root for source connectors."""

from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.flotta import flotta_connectors
from treasureiq.catalog.service_portal_connector import ServicePortalConnettore
from treasureiq.catalog.wordpress_connector import WordPressAgidConnector
from treasureiq.catalog.web_connector import WebScrapeConnector


def default_connector_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(WordPressAgidConnector())
    # Fleet units (municipium/comweb/peopleweb × BASE/AT) win for their own
    # platforms; they must precede the wildcard WebScrape fallback so a served
    # platform gets MEDIATED structured data, not an INDIRECT scrape.
    for connector in flotta_connectors():
        registry.register(connector)
    # SERVICE_PORTAL surface: disjoint from the scrape capabilities, order-free.
    registry.register(ServicePortalConnettore())
    registry.register(WebScrapeConnector())
    return registry
