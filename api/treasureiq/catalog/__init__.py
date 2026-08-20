"""Versioned backoffice catalog contracts.

The catalog is intentionally isolated from the v0 runtime.  It describes what
was measured about a source; it does not fetch, normalize, or answer chat
requests.
"""

from treasureiq.catalog.adapters import (
    AdapterRegistry,
    CatalogAdapter,
    WebScrapeAdapter,
    WordPressAgidAdapter,
    default_adapter_registry,
)
from treasureiq.catalog.contracts import (
    AccessContract,
    AccessMode,
    AgidCompatibility,
    CapabilityStatus,
    ConnectorContract,
    FreshnessStatus,
    SectionStatus,
    Surface,
)
from treasureiq.catalog.connectors import ConnectorResult, SourceConnector
from treasureiq.catalog.connector_defaults import default_connector_registry
from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.wordpress_connector import WordPressAgidConnector
from treasureiq.catalog.web_connector import WebScrapeConnector
from treasureiq.catalog.scraping import HtmlScrapeEngine, ScrapeEngine, ScrapeResult
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataBatch,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
    FreshnessPolicy,
    RequestLimits,
    TransportMeta,
)
from treasureiq.catalog.drift import DriftEvent, DriftKind, compare_snapshots
from treasureiq.catalog.planner import QueryPlan, QueryStep, build_query_plan, select_batch
from treasureiq.catalog.plugins import CapabilityManifest, PluginManifest
from treasureiq.catalog.registry import PlatformRegistry
from treasureiq.catalog.shadow import municipality_snapshots, platform_snapshot
from treasureiq.catalog.shadow_run import persist_shadow_snapshots
from treasureiq.catalog.snapshots import (
    MunicipalityPlatformSnapshot,
    PlatformSnapshot,
)
from treasureiq.catalog.store import SnapshotStore

__all__ = [
    "AccessContract",
    "AccessMode",
    "AdapterRegistry",
    "AgidCompatibility",
    "CapabilityStatus",
    "ConnectorContract",
    "ConnectorRef",
    "ConnectorResult",
    "ConnectorRegistry",
    "CatalogAdapter",
    "SourceConnector",
    "default_connector_registry",
    "CapabilityManifest",
    "WordPressAgidAdapter",
    "WordPressAgidConnector",
    "WebScrapeConnector",
    "ScrapeEngine",
    "ScrapeResult",
    "HtmlScrapeEngine",
    "WebScrapeAdapter",
    "DataBatch",
    "DataRequest",
    "DataStatus",
    "DriftEvent",
    "DriftKind",
    "FreshnessStatus",
    "Freshness",
    "FreshnessPolicy",
    "EvidenceRef",
    "RequestLimits",
    "MunicipalityPlatformSnapshot",
    "PlatformSnapshot",
    "PlatformRegistry",
    "PluginManifest",
    "QueryPlan",
    "QueryStep",
    "SnapshotStore",
    "SectionStatus",
    "Surface",
    "TransportMeta",
    "compare_snapshots",
    "build_query_plan",
    "default_adapter_registry",
    "municipality_snapshots",
    "platform_snapshot",
    "persist_shadow_snapshots",
    "select_batch",
]
