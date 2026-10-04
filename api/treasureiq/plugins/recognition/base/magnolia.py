"""Firma BASE del tema civico Magnolia/Kibernetes osservata sui siti comunali."""

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

_RISORSE = re.compile(r"/\.resources/kibernetes/", re.I)
_IMAGING = re.compile(r"/\.imaging/mte/kibernetes/", re.I)
_HEAD_LIMIT = 16_384


class MagnoliaRecognitionPlugin:
    manifest = RecognitionPluginManifest(
        plugin_id="magnolia_base",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="magnolia-kibernetes-v1",
        surface=Surface.ORDINARY_DATA,
        platforms=("magnolia",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        head = observation.body[:_HEAD_LIMIT]
        # Le due rotte di asset appartengono allo stesso tema Kibernetes.
        # Chiederle insieme evita di attribuire Magnolia a un link isolato.
        if not (_RISORSE.search(head) and _IMAGING.search(head)):
            return RecognitionPluginResult(recognition_score=0.0)
        descrizione = "asset Kibernetes: .resources e .imaging"
        return RecognitionPluginResult(
            platform_id="magnolia",
            recognition_score=0.99,
            confidence=RecognitionConfidence.HIGH,
            fingerprint="sha256:" + hashlib.sha256(descrizione.encode()).hexdigest(),
            evidence=(FingerprintEvidence(
                key="kibernetes_assets", description=descrizione, matched=True,
                weight=0.99, observed="/.resources/kibernetes/ + /.imaging/mte/kibernetes/",
            ),),
        )


MAGNOLIA_RECOGNITION_PLUGIN = MagnoliaRecognitionPlugin()
