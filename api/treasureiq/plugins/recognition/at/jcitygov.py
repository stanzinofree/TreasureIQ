"""Native TRANSPARENCY recognition for the jcitygov Amministrazione Trasparente.

jcitygov's transparency surface is a SaaS portal independent of the base CMS
(WordPress at Peveragno, Municipium at Chieri/Grugliasco). It betrays itself
only through the vendor host ``trasparenza-valutazione-merito.it`` that serves
its assets — an involuntary, unshared host signature the legacy classifier
treats as *definitive*. This plugin mirrors that rule so it matches the v1
bridge on the same sample.
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
# Same per-table rank the legacy classifier assigns ``host_prodotto`` (see
# ``ingest.piattaforma._RANGO_TAVOLA``); keeping it identical is what makes the
# native score equal the bridge score on the shared fixture.
_RANK_HOST = 5
_EPSILON = 0.1

#: Vendor host that serves jcitygov's AT assets. A host signature nobody else
#: writes — definitive, unlike a shared route or a generic asset path.
_JCITYGOV_HOST = re.compile(r"trasparenza-valutazione-merito\.it", re.I)


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


class JcitygovAtRecognitionPlugin:
    """Recognize jcitygov AT evidence without network or legacy imports."""

    manifest = RecognitionPluginManifest(
        plugin_id="jcitygov_at",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="jcitygov-at-v1",
        surface=Surface.TRANSPARENCY,
        platforms=("jcitygov",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        body = observation.body[:_BODY_LIMIT]

        host = _JCITYGOV_HOST.search(body)
        if not host:
            return RecognitionPluginResult(recognition_score=0.0)

        score = _score(_DEFINITIVE, _RANK_HOST)
        description = f"asset host: {host.group(0)}"
        evidence = (
            FingerprintEvidence(
                key="host_prodotto",
                description=description,
                matched=True,
                weight=score,
                observed=host.group(0),
            ),
        )
        fingerprint = "sha256:" + hashlib.sha256(
            f"host_prodotto:{host.group(0)}".encode()
        ).hexdigest()
        return RecognitionPluginResult(
            platform_id="jcitygov",
            recognition_score=score,
            confidence=_confidence(score),
            fingerprint=fingerprint,
            evidence=evidence,
        )


PLUGIN = JcitygovAtRecognitionPlugin()
JCITYGOV_AT_RECOGNITION_PLUGIN = PLUGIN
