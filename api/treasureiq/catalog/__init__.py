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
from treasureiq.catalog.service_contracts import (
    AuthenticationMethod,
    ServiceAccessMode,
    ServiceAccessOption,
    ServicePortalCandidate,
    ServicePortalRole,
    ServiceReference,
    SourceInventory,
)
from treasureiq.catalog.connectors import ConnectorResult, SourceConnector
from treasureiq.catalog.connector_defaults import default_connector_registry
from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.wordpress_connector import WordPressAgidConnector
from treasureiq.catalog.web_connector import WebScrapeConnector
from treasureiq.catalog.scraping import HtmlScrapeEngine, ScrapeEngine, ScrapeResult
from treasureiq.catalog.runtime import CatalogRuntime, batch_from_connector_result
from treasureiq.catalog.fallback_store import FallbackRunStore
from treasureiq.catalog.sweep_bridge import snapshots_from_sweep_db, snapshots_from_sweep_row
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
from treasureiq.catalog.planner import (
    QueryPlan,
    QueryStep,
    build_query_plan,
    request_from_recognition,
    service_portal_request,
    select_batch,
)
from treasureiq.catalog.plugins import CapabilityManifest, PluginManifest
from treasureiq.catalog.recognition import (
    ConnectorVersionManifest,
    FingerprintEvidence,
    RecognitionAction,
    RecognitionConfidence,
    RecognitionResult,
    ResweepPolicy,
    action_for_recognition,
    score_evidence,
)
from treasureiq.catalog.recognition_plugins import (
    RecognitionObservation,
    RecognitionPlugin,
    RecognitionPluginManifest,
    RecognitionPluginResult,
)
from treasureiq.catalog.recognition_registry import (
    RecognitionMatch,
    RecognitionRegistry,
    build_recognition_result,
)
from treasureiq.catalog.recognition_bridge import (
    LegacyRecognitionBridge,
    build_bridge_registry,
)
from treasureiq.catalog.checks import CheckResult, CheckStatus, source_identity_check
from treasureiq.catalog.confirmation import confirm_inventory
from treasureiq.catalog.discovery_profiles import DiscoveryProfile, profile_for_base
from treasureiq.catalog.inventory_discovery import discover_source_inventory
from treasureiq.catalog.service_portals import group_service_portal_candidates
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
    "AuthenticationMethod",
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
    "CheckResult",
    "CheckStatus",
    "ConnectorVersionManifest",
    "FingerprintEvidence",
    "WordPressAgidAdapter",
    "WordPressAgidConnector",
    "WebScrapeConnector",
    "ScrapeEngine",
    "ScrapeResult",
    "HtmlScrapeEngine",
    "CatalogRuntime",
    "batch_from_connector_result",
    "FallbackRunStore",
    "snapshots_from_sweep_row",
    "snapshots_from_sweep_db",
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
    "RecognitionAction",
    "RecognitionConfidence",
    "RecognitionResult",
    "RecognitionObservation",
    "RecognitionPlugin",
    "RecognitionPluginManifest",
    "RecognitionPluginResult",
    "RecognitionMatch",
    "RecognitionRegistry",
    "build_recognition_result",
    "LegacyRecognitionBridge",
    "build_bridge_registry",
    "QueryPlan",
    "QueryStep",
    "SnapshotStore",
    "SectionStatus",
    "ServiceAccessMode",
    "ServiceAccessOption",
    "ServicePortalCandidate",
    "ServicePortalRole",
    "ServiceReference",
    "SourceInventory",
    "ResweepPolicy",
    "Surface",
    "TransportMeta",
    "compare_snapshots",
    "build_query_plan",
    "request_from_recognition",
    "service_portal_request",
    "default_adapter_registry",
    "municipality_snapshots",
    "platform_snapshot",
    "persist_shadow_snapshots",
    "select_batch",
    "action_for_recognition",
    "score_evidence",
    "source_identity_check",
    "confirm_inventory",
    "DiscoveryProfile",
    "profile_for_base",
    "discover_source_inventory",
    "group_service_portal_candidates",
]
