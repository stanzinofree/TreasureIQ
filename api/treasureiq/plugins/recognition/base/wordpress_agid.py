"""Native BASE recognition for the WordPress family used by the connector.

This plugin recognizes only evidence that the legacy BASE classifier already
considers WordPress evidence.  ``wordpress_agid`` is the acquisition connector
and is deliberately not returned as a platform identity: the observed
platform remains ``wordpress_generico`` until a more specific fingerprint is
available.
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


_HEAD_LIMIT = 8_192
_ASSET_LIMIT = 40_000
_DEFINITIVE = 100.0
_EURISTIC = 50.0
_RANK_GENERATOR = 2
_RANK_LINK_API = 3
_RANK_ASSET = 7
_EPSILON = 0.1

_META_GENERATOR = re.compile(
    r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"'](?P<v>[^\"']{1,120})",
    re.I,
)
_LINK_WP_API = re.compile(r"<link[^>]+https://api\.w\.org/", re.I)
_WP_ASSET = re.compile(r"/wp-(?:content|includes)/", re.I)
_WORDPRESS = re.compile(r"\bWordPress\b", re.I)


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


class WordPressAgidRecognitionPlugin:
    """Recognize WordPress BASE evidence without network or legacy imports."""

    manifest = RecognitionPluginManifest(
        plugin_id="wordpress_agid_base",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="wordpress-base-v1",
        surface=Surface.ORDINARY_DATA,
        platforms=("wordpress_generico",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        head = observation.body[:_HEAD_LIMIT]
        body = observation.body[:_ASSET_LIMIT]
        matches: list[tuple[str, str, float]] = []

        generator = _META_GENERATOR.search(head)
        if generator and _WORDPRESS.search(generator.group("v")):
            value = generator.group("v")
            matches.append(("generator", f"generator: {value}", _score(_EURISTIC, _RANK_GENERATOR)))

        if _LINK_WP_API.search(head):
            matches.append(("link_wp_api", "link rel=https://api.w.org/", _score(_DEFINITIVE, _RANK_LINK_API)))

        asset = _WP_ASSET.search(body)
        if asset:
            matches.append(("asset", f"asset: {asset.group(0)}", _score(_EURISTIC, _RANK_ASSET)))

        if not matches:
            return RecognitionPluginResult(recognition_score=0.0)

        winner = max(matches, key=lambda item: item[2])
        evidence = tuple(
            FingerprintEvidence(
                key=key,
                description=description,
                matched=key == winner[0],
                weight=score,
                observed=description,
            )
            for key, description, score in matches
        )
        fingerprint_payload = "|".join(f"{key}:{description}" for key, description, _ in matches)
        fingerprint = "sha256:" + hashlib.sha256(fingerprint_payload.encode()).hexdigest()
        return RecognitionPluginResult(
            platform_id="wordpress_generico",
            recognition_score=winner[2],
            confidence=_confidence(winner[2]),
            fingerprint=fingerprint,
            evidence=evidence,
        )


PLUGIN = WordPressAgidRecognitionPlugin()
