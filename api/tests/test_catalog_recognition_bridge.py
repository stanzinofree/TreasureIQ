"""Golden parity for the v1 recognition bridge.

The bridge must be a lossless wrapper: whatever ``classifica_risposta`` elects
as the platform for a given surface, the registry must return through the
bridge. These fixtures are the same real portal responses the classifier test
suite freezes, so a divergence here is a genuine regression in the seam, not a
brittle string assertion.

``compare_to_bridge`` is the harness a future native plugin reuses: extract a
family, then assert the plugin agrees with the bridge on the same observation
before it is allowed to win in the registry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import RecognitionAction
from treasureiq.catalog.recognition_bridge import (
    LegacyRecognitionBridge,
    build_bridge_registry,
)
from treasureiq.catalog.recognition_plugins import (
    RecognitionObservation,
    RecognitionPlugin,
    RecognitionPluginResult,
)
from treasureiq.catalog.recognition_registry import build_recognition_result
from treasureiq.ingest.piattaforma import classifica_risposta

_FIXTURE_AT = Path(__file__).parent / "fixtures" / "at"
_ENTRYPOINT = "https://comune.example.it/"


def _observe(surface: Surface, *, body: str = "", **headers: str) -> RecognitionObservation:
    return RecognitionObservation(
        source_id="058003",
        surface=surface,
        entrypoint_url=_ENTRYPOINT,
        http_status=200,
        headers=headers,
        body=body,
    )


def compare_to_bridge(
    plugin: RecognitionPlugin, observation: RecognitionObservation
) -> tuple[RecognitionPluginResult, RecognitionPluginResult]:
    """Run a candidate plugin and the surface bridge on the same observation.

    Returns ``(plugin_result, bridge_result)`` so a family-extraction test can
    assert equivalence on ``platform_id``/``recognition_score`` before flipping
    the plugin on in the registry.
    """
    bridge = LegacyRecognitionBridge(observation.surface)
    return plugin.recognize(observation), bridge.recognize(observation)


def test_bridge_base_agrees_with_classifier_on_wordpress():
    body = '<html><head><link rel="stylesheet" href="/wp-content/themes/x/s.css"></head>'
    observation = _observe(Surface.ORDINARY_DATA, body=body)
    result = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(observation)
    winner = classifica_risposta(headers={}, html=body, includi_at=False).vincitore
    assert result.platform_id == winner.piattaforma.value == "wordpress_generico"
    assert 0.0 < result.recognition_score <= 1.0
    assert any(e.matched and e.key == "wordpress_generico" for e in result.evidence)


def test_bridge_base_excludes_at_family_like_classifier():
    """Peveragno home: an outbound AT link must not elect jcitygov on BASE, and
    the bridge must inherit that ``includi_at=False`` exclusion verbatim."""
    body = (_FIXTURE_AT / "peveragno_jcitygov_head.html").read_text(encoding="utf-8")
    observation = _observe(Surface.ORDINARY_DATA, body=body)
    result = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(observation)
    winner = classifica_risposta(headers={}, html=body, includi_at=False).vincitore
    # AT-family must never win on BASE; a sentinel winner maps to None.
    assert result.platform_id != "jcitygov"
    if winner.piattaforma.value in {"ignota", "non_misurata", "non_trovata"}:
        assert result.platform_id is None
    else:
        assert result.platform_id == winner.piattaforma.value
    assert any(e.key == "jcitygov" for e in result.evidence)


def test_bridge_header_signature_needs_no_body():
    observation = _observe(Surface.ORDINARY_DATA, body="<html></html>", **{"x-drupal-cache": "HIT"})
    result = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(observation)
    assert result.platform_id == "drupal"
    # A definitive signature scores just under 1.0 (per-table rank penalty).
    assert result.recognition_score >= 0.99
    assert result.confidence.value == "high"


def test_bridge_unknown_maps_to_none_not_sentinel():
    observation = _observe(Surface.ORDINARY_DATA, body="<html><head></head><body></body></html>")
    result = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(observation)
    assert result.platform_id is None
    assert result.recognition_score == 0.0
    assert result.confidence.value == "unknown"


def test_registry_routes_by_surface_and_wraps_result():
    registry = build_bridge_registry()
    # Definitive signature (linked REST API) so the action policy lands on KEEP.
    body = '<html><head><link rel="https://api.w.org/" href="/wp-json/"></head>'
    observation = _observe(Surface.ORDINARY_DATA, body=body)
    match = registry.recognize(observation)
    assert match is not None
    assert match.result.platform_id == "wordpress_generico"
    assert match.manifest.plugin_id == "legacy_bridge_ordinary_data"

    checked_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    record = build_recognition_result(observation, match, checked_at=checked_at)
    assert record.source_id == "058003"
    assert record.connector_id == "legacy_bridge_ordinary_data"
    assert record.platform_id == "wordpress_generico"
    assert record.action is RecognitionAction.KEEP
    assert record.checked_at == checked_at


def test_registry_none_platform_forces_manual_review():
    registry = build_bridge_registry()
    observation = _observe(Surface.ORDINARY_DATA, body="<html></html>")
    match = registry.recognize(observation)
    assert match is not None and match.result.platform_id is None
    record = build_recognition_result(
        observation, match, checked_at=datetime(2026, 8, 21, tzinfo=UTC)
    )
    assert record.action is RecognitionAction.MANUAL_REVIEW


def test_registry_preserves_plugin_fingerprint():
    registry = build_bridge_registry()
    observation = _observe(Surface.ORDINARY_DATA, body="<html></html>")
    match = registry.recognize(observation)
    assert match is not None

    class _FingerprintPlugin:
        manifest = LegacyRecognitionBridge(Surface.ORDINARY_DATA).manifest.model_copy(
            update={
                "plugin_id": "fingerprint_test",
                "version": "1.2.3",
                "fingerprint_version": "fp-2",
                "platforms": ("test_platform",),
            }
        )

        def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
            return RecognitionPluginResult(
                platform_id="test_platform",
                recognition_score=1.0,
                fingerprint="sha256:test",
            )

    registry.register(_FingerprintPlugin())
    native_observation = observation.model_copy(
        update={"expected_platform": "test_platform"}
    )
    native_match = registry.recognize(native_observation)
    assert native_match is not None
    record = build_recognition_result(
        native_observation,
        native_match,
        checked_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert record.fingerprint == "sha256:test"
    assert record.fingerprint_version == "fp-2"


def test_registry_rejects_duplicate_registration():
    registry = build_bridge_registry()
    with pytest.raises(ValueError):
        registry.register(LegacyRecognitionBridge(Surface.ORDINARY_DATA))


class _StubNativePlugin:
    """Minimal native plugin to prove native beats the wildcard bridge on tie."""

    def __init__(self) -> None:
        self.manifest = LegacyRecognitionBridge(Surface.ORDINARY_DATA).manifest.model_copy(
            update={"plugin_id": "wordpress_native", "platforms": ("wordpress_generico",)}
        )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        return RecognitionPluginResult(
            platform_id="wordpress_generico", recognition_score=1.0
        )


def test_native_plugin_wins_tie_over_bridge():
    registry = build_bridge_registry()
    registry.register(_StubNativePlugin())
    body = '<html><head><link rel="stylesheet" href="/wp-content/themes/x/s.css"></head>'
    observation = _observe(Surface.ORDINARY_DATA, body=body, **{"role": "personal_area"})
    observation = observation.model_copy(update={"base_platform_hint": "wordpress_generico"})
    match = registry.recognize(observation)
    assert match is not None
    assert match.manifest.plugin_id == "wordpress_native"
