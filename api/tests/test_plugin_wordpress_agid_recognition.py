from __future__ import annotations

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition_bridge import LegacyRecognitionBridge
from treasureiq.catalog.recognition_plugins import RecognitionObservation
from treasureiq.plugins.recognition.base.wordpress_agid import PLUGIN


def _observation(body: str, **headers: str) -> RecognitionObservation:
    return RecognitionObservation(
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        entrypoint_url="https://comune.example.it/",
        http_status=200,
        headers=headers,
        body=body,
    )


def test_wordpress_native_plugin_matches_bridge_on_rest_signature() -> None:
    observation = _observation(
        '<html><head><link rel="https://api.w.org/" href="/wp-json/"></head>'
    )
    native = PLUGIN.recognize(observation)
    legacy = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(observation)
    assert native.platform_id == legacy.platform_id == "wordpress_generico"
    assert native.recognition_score == legacy.recognition_score
    assert native.confidence is legacy.confidence
    assert native.fingerprint is not None


def test_wordpress_native_plugin_matches_bridge_on_asset_signature() -> None:
    observation = _observation(
        '<html><head><link rel="stylesheet" href="/wp-content/themes/x/style.css"></head>'
    )
    native = PLUGIN.recognize(observation)
    legacy = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(observation)
    assert native.platform_id == legacy.platform_id == "wordpress_generico"
    assert native.recognition_score == legacy.recognition_score


def test_wordpress_native_plugin_does_not_claim_unrelated_html() -> None:
    result = PLUGIN.recognize(_observation("<html><body>Comune</body></html>"))
    assert result.platform_id is None
    assert result.recognition_score == 0.0
