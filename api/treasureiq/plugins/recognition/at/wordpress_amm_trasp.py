"""Native TRANSPARENCY recognition for the WordPress amm_trasp plugin.

Many WordPress comuni expose Amministrazione Trasparente through a dedicated
custom post type whose archive body carries the ``post-type-archive-amm_trasp``
class. The legacy classifier treats that body class as a *definitive* AT
signature. This plugin mirrors that rule and score so it matches the v1 bridge
on the same sample.
"""

from __future__ import annotations

import hashlib
import re

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import FingerprintEvidence, RecognitionConfidence
from treasureiq.catalog.recognition_plugins import (
    RecognitionObservation,
    RecognitionPluginManifest,
    RecognitionPluginResult,
)


_BODY_LIMIT = 40_000
_DEFINITIVE = 100.0
# Same per-table rank the legacy classifier assigns ``wp_amm_trasp`` (see
# ``ingest.piattaforma._RANGO_TAVOLA``); keeping it identical makes the native
# score equal the bridge score on the shared fixture.
_RANK_WP_AMM_TRASP = 8
_EPSILON = 0.1

#: The custom-post-type archive body class WordPress emits for the AT section.
_WP_AMM_TRASP = re.compile(r"post-type-archive-amm_trasp", re.I)


def _score(raw: float, rank: int) -> float:
    return (raw - rank * _EPSILON) / 100.0


def _confidence(score: float) -> RecognitionConfidence:
    if score >= 0.75:
        return RecognitionConfidence.HIGH
    if score >= 0.25:
        return RecognitionConfidence.MEDIUM
    if score > 0.0:
        return RecognitionConfidence.LOW
    return RecognitionConfidence.UNKNOWN


class WordPressAmmTraspRecognitionPlugin:
    """Recognize WordPress AT evidence without network or legacy imports."""

    manifest = RecognitionPluginManifest(
        plugin_id="wordpress_amm_trasp_at",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="wordpress-amm-trasp-at-v1",
        surface=Surface.TRANSPARENCY,
        platforms=("wp_amm_trasp",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        body = observation.body[:_BODY_LIMIT]

        marker = _WP_AMM_TRASP.search(body)
        if not marker:
            return RecognitionPluginResult(recognition_score=0.0)

        score = _score(_DEFINITIVE, _RANK_WP_AMM_TRASP)
        description = f"body class: {marker.group(0)}"
        evidence = (
            FingerprintEvidence(
                key="wp_amm_trasp",
                description=description,
                matched=True,
                weight=score,
                observed=marker.group(0),
            ),
        )
        fingerprint = "sha256:" + hashlib.sha256(
            f"wp_amm_trasp:{marker.group(0)}".encode()
        ).hexdigest()
        return RecognitionPluginResult(
            platform_id="wp_amm_trasp",
            recognition_score=score,
            confidence=_confidence(score),
            fingerprint=fingerprint,
            evidence=evidence,
        )


PLUGIN = WordPressAmmTraspRecognitionPlugin()
WORDPRESS_AMM_TRASP_RECOGNITION_PLUGIN = PLUGIN
