"""Native TRANSPARENCY recognition for the URBI Amministrazione Trasparente.

URBI's transparency surface is a SaaS portal reached through the application
route ``ur1UR033.sto``.  The legacy classifier treats that route as a
*definitive* signature and deliberately does NOT accept a bare ``/urbi/`` asset
path: Bootstrap styling from the portal can leak into a BASE page without the
page actually being URBI AT.  This plugin mirrors that rule exactly — only the
functional route is evidence — so it matches the v1 bridge on the same sample.
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
# Same per-table rank the legacy classifier assigns ``urbi_at`` (see
# ``ingest.piattaforma._RANGO_TAVOLA``).  Keeping it identical is what makes
# the native score equal the bridge score on the shared fixture.
_RANK_URBI_AT = 11
_EPSILON = 0.1

#: The URBI AT application route. A functional signature of the surface, not a
#: generic ``/urbi/`` asset — a BASE page embedding only the portal's Bootstrap
#: style must not be claimed as URBI AT.
_URBI_AT = re.compile(r"ur1UR033\.sto", re.I)


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


class UrbiAtRecognitionPlugin:
    """Recognize URBI AT evidence without network or legacy imports."""

    manifest = RecognitionPluginManifest(
        plugin_id="urbi_at",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="urbi-at-v1",
        surface=Surface.TRANSPARENCY,
        platforms=("urbi",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        body = observation.body[:_BODY_LIMIT]

        route = _URBI_AT.search(body)
        if not route:
            return RecognitionPluginResult(recognition_score=0.0)

        score = _score(_DEFINITIVE, _RANK_URBI_AT)
        description = f"rotta URBI AT: {route.group(0)}"
        evidence = (
            FingerprintEvidence(
                key="urbi_at",
                description=description,
                matched=True,
                weight=score,
                observed=route.group(0),
            ),
        )
        fingerprint = "sha256:" + hashlib.sha256(
            f"urbi_at:{route.group(0)}".encode()
        ).hexdigest()
        return RecognitionPluginResult(
            platform_id="urbi",
            recognition_score=score,
            confidence=_confidence(score),
            fingerprint=fingerprint,
            evidence=evidence,
        )


PLUGIN = UrbiAtRecognitionPlugin()
URBI_AT_RECOGNITION_PLUGIN = PLUGIN
