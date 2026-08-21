"""Native BASE recognition for ComWeb (ePublic).

Unlike PeopleWeb (a silent, unbranded product), ComWeb declares itself in the
``generator`` meta tag. The legacy classifier treats every named generator as
*definitive* — only bare ``WordPress`` is heuristic — so a ``ComWeb`` generator
is a definitive BASE signature. This plugin mirrors that rule and score so it
matches the v1 bridge on the same sample.
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
_DEFINITIVE = 100.0
# Same per-table rank the legacy classifier assigns a ``generator`` match (see
# ``ingest.piattaforma._RANGO_TAVOLA``); keeping it identical makes the native
# score equal the bridge score on the shared fixture.
_RANK_GENERATOR = 2
_EPSILON = 0.1

_META_GENERATOR = re.compile(
    r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"'](?P<v>[^\"']{1,120})",
    re.I,
)
#: ComWeb declares itself by name in the generator content.
_COMWEB = re.compile(r"\bComWeb\b", re.I)


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


class ComWebRecognitionPlugin:
    """Recognize ComWeb BASE evidence without network or legacy imports."""

    manifest = RecognitionPluginManifest(
        plugin_id="comweb_base",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="comweb-base-v1",
        surface=Surface.ORDINARY_DATA,
        platforms=("comweb",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        head = observation.body[:_HEAD_LIMIT]

        generator = _META_GENERATOR.search(head)
        if not (generator and _COMWEB.search(generator.group("v"))):
            return RecognitionPluginResult(recognition_score=0.0)

        value = generator.group("v")
        score = _score(_DEFINITIVE, _RANK_GENERATOR)
        description = f"generator: {value}"
        evidence = (
            FingerprintEvidence(
                key="generator",
                description=description,
                matched=True,
                weight=score,
                observed=value,
            ),
        )
        fingerprint = "sha256:" + hashlib.sha256(
            f"generator:{value}".encode()
        ).hexdigest()
        return RecognitionPluginResult(
            platform_id="comweb",
            recognition_score=score,
            confidence=_confidence(score),
            fingerprint=fingerprint,
            evidence=evidence,
        )


PLUGIN = ComWebRecognitionPlugin()
COMWEB_RECOGNITION_PLUGIN = PLUGIN
