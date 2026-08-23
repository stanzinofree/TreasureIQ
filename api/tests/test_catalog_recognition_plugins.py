from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import RecognitionConfidence
from treasureiq.catalog.recognition_plugins import (
    RecognitionObservation,
    RecognitionPluginManifest,
    RecognitionPluginResult,
)


def test_recognition_plugin_contract_is_surface_scoped() -> None:
    manifest = RecognitionPluginManifest(
        plugin_id="wordpress_agid_base",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="1.0",
        surface=Surface.ORDINARY_DATA,
        platforms=("wordpress_agid",),
    )
    observation = RecognitionObservation(
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        entrypoint_url="https://comune.example.it/",
        http_status=200,
        body="<html>",
    )
    result = RecognitionPluginResult(
        platform_id="wordpress_agid",
        recognition_score=1.0,
        confidence=RecognitionConfidence.HIGH,
    )
    assert manifest.surface is observation.surface
    assert result.platform_id == "wordpress_agid"
