"""v1 legacy bridge exposing ``ingest.piattaforma`` as a recognition plugin.

This is core-owned migration scaffolding, not a workspace plugin: it is the one
place allowed to import ``ingest`` because it *is* the bridge the doctrine keeps
alive until each family has a native plugin that matches it on fixtures. When a
native plugin for a platform is registered, its explicit ``platforms`` tuple
beats this wildcard bridge on a score tie (see ``RecognitionRegistry``), so the
bridge quietly stops owning that platform without a rewrite.

The bridge performs no network I/O: it only re-reads the already-fetched
``RecognitionObservation`` body and headers.
"""

from __future__ import annotations

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import (
    FingerprintEvidence,
    RecognitionConfidence,
    ResweepPolicy,
)
from treasureiq.catalog.recognition_plugins import (
    RecognitionObservation,
    RecognitionPluginManifest,
    RecognitionPluginResult,
)

# Mirror of ingest.piattaforma's ``_SCORE_DEFINITIVO``/``_SCORE_EURISTICO``.
# A definitive signature scores just under 100 (``_score`` subtracts a tiny
# per-table rank), so confidence is bucketed by class against the midpoints,
# never by an exact 1.0 that the classifier never actually returns.
_MAX_SCORE = 100.0
_HIGH_FLOOR = 75.0  # midpoint of definitivo (100) and euristico (50)
_MEDIUM_FLOOR = 25.0  # half of euristico

# The legacy classifier reports "we did not recognise anything" through these
# enum values. They must never surface as a platform_id.
_NON_PLATFORMS = frozenset({"ignota", "non_misurata", "non_trovata"})

# AT and service portals are the only surfaces where an AT-family signature may
# win. BASE callers (home sweep, connector) run with ``includi_at=False``.
_AT_SURFACES = frozenset({Surface.TRANSPARENCY, Surface.SERVICE_PORTAL})

_BRIDGE_VERSION = "1.0.0"


def _confidence(raw_score: float) -> RecognitionConfidence:
    if raw_score >= _HIGH_FLOOR:
        return RecognitionConfidence.HIGH
    if raw_score >= _MEDIUM_FLOOR:
        return RecognitionConfidence.MEDIUM
    if raw_score > 0.0:
        return RecognitionConfidence.LOW
    return RecognitionConfidence.UNKNOWN


class LegacyRecognitionBridge:
    """Wrap ``classifica_risposta`` for one surface as a wildcard plugin."""

    def __init__(self, surface: Surface) -> None:
        self._surface = surface
        self._includi_at = surface in _AT_SURFACES
        self.manifest = RecognitionPluginManifest(
            plugin_id=f"legacy_bridge_{surface.value}",
            version=_BRIDGE_VERSION,
            contract_version="recognition.v1",
            fingerprint_version="piattaforma.v1",
            surface=surface,
            platforms=("*",),
        )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        # Imported lazily: only the bridge is permitted to reach into ingest,
        # and only when actually asked to recognise something.
        from treasureiq.ingest.piattaforma import classifica_risposta

        esito = classifica_risposta(
            headers=dict(observation.headers),
            html=observation.body,
            includi_at=self._includi_at,
        )
        vincitore = esito.vincitore
        platform = vincitore.piattaforma.value

        evidence = tuple(
            FingerprintEvidence(
                key=firma.piattaforma.value,
                description=firma.prova or firma.piattaforma.value,
                matched=firma.piattaforma is vincitore.piattaforma,
                weight=min(firma.score / _MAX_SCORE, 1.0),
                observed=firma.prova,
            )
            for firma in esito.scattate
        )

        if platform in _NON_PLATFORMS:
            return RecognitionPluginResult(
                platform_id=None,
                recognition_score=0.0,
                confidence=RecognitionConfidence.UNKNOWN,
                evidence=evidence,
            )

        winning = next(
            (f for f in esito.scattate if f.piattaforma is vincitore.piattaforma),
            None,
        )
        raw = winning.score if winning else 0.0
        return RecognitionPluginResult(
            platform_id=platform,
            recognition_score=min(raw / _MAX_SCORE, 1.0),
            confidence=_confidence(raw),
            evidence=evidence,
        )


def build_bridge_registry():
    """Return a registry seeded with the v1 bridge for BASE, AT and SP.

    BASE maps to ``ORDINARY_DATA`` to match the existing plugin tests; the AT
    and service-portal surfaces are the ones that run with ``includi_at=True``.
    """
    from treasureiq.catalog.recognition_registry import RecognitionRegistry

    registry = RecognitionRegistry()
    for surface in (
        Surface.ORDINARY_DATA,
        Surface.TRANSPARENCY,
        Surface.SERVICE_PORTAL,
    ):
        registry.register(LegacyRecognitionBridge(surface))
    return registry


# Agreed BASE recognition policy (plan.md, "soglia concordata" 2026-08-21).
# Heuristic-only WordPress — a lone meta generator or a surviving /wp-content
# asset, scoring ~0.49 — is genuine but weak evidence: the classifier itself
# warns a stray /wp-content can be the echo of a previous CMS. It must trigger
# an automatic REDISCOVER (one fetch, no human), never a MANUAL_REVIEW, so
# hardened installs like Albano keep flowing exactly as they do under the v1
# bridge. Only an empty recognition (platform None) reaches manual review.
BASE_RECOGNITION_POLICY = ResweepPolicy(manual_review_below=0.40)


def build_recognition_registry():
    """Production registry: the v1 bridge plus every activated native plugin.

    A native plugin beats the wildcard bridge on a score tie, so an activated
    family stops being served by the bridge the moment it registers — without
    removing the bridge, which stays the safety net until a later release
    retires the migrated signature.
    """
    from treasureiq.plugins.recognition.at import (
        JCITYGOV_AT_RECOGNITION_PLUGIN,
        URBI_AT_RECOGNITION_PLUGIN,
        WORDPRESS_AMM_TRASP_RECOGNITION_PLUGIN,
    )
    from treasureiq.plugins.recognition.base import (
        COMWEB_RECOGNITION_PLUGIN,
        WORDPRESS_AGID_RECOGNITION_PLUGIN,
    )
    from treasureiq.plugins.recognition.service_portal import (
        MUNICIPIUM_PORTALEGEN_RECOGNITION_PLUGIN,
    )

    registry = build_bridge_registry()
    registry.register(WORDPRESS_AGID_RECOGNITION_PLUGIN)
    registry.register(COMWEB_RECOGNITION_PLUGIN)
    registry.register(URBI_AT_RECOGNITION_PLUGIN)
    registry.register(JCITYGOV_AT_RECOGNITION_PLUGIN)
    registry.register(WORDPRESS_AMM_TRASP_RECOGNITION_PLUGIN)
    registry.register(MUNICIPIUM_PORTALEGEN_RECOGNITION_PLUGIN)
    return registry
