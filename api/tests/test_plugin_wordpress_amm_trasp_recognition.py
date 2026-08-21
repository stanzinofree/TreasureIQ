"""T1 native plugin: WordPress amm_trasp (TRANSPARENCY surface).

Obligatory matrix: match, false positive, score/confidence, verbatim evidence,
incomplete HTML, no network, fingerprint version. Plus parity with the v1
bridge on the same fixture.
"""

from __future__ import annotations

import pytest

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import RecognitionConfidence
from treasureiq.catalog.recognition_bridge import LegacyRecognitionBridge
from treasureiq.catalog.recognition_plugins import RecognitionObservation
from treasureiq.plugins.recognition.at.wordpress_amm_trasp import PLUGIN


def _observation(body: str, **headers: str) -> RecognitionObservation:
    return RecognitionObservation(
        source_id="099998",
        surface=Surface.TRANSPARENCY,
        entrypoint_url="https://comune.example.it/amministrazione-trasparente",
        http_status=200,
        headers=headers,
        body=body,
    )


_AT_PAGE = (
    '<html><body class="post-type-archive post-type-archive-amm_trasp">'
    "Amministrazione Trasparente</body></html>"
)


def test_wp_amm_trasp_plugin_matches_body_class() -> None:
    result = PLUGIN.recognize(_observation(_AT_PAGE))
    assert result.platform_id == "wp_amm_trasp"
    assert result.confidence is RecognitionConfidence.HIGH
    # (100 - 8*0.1)/100 — definitive, minus the wp_amm_trasp table rank.
    assert result.recognition_score == pytest.approx(0.992)


def test_wp_amm_trasp_plugin_ignores_plain_wordpress_at() -> None:
    body = '<html><body class="post-type-archive">Trasparenza</body></html>'
    result = PLUGIN.recognize(_observation(body))
    assert result.platform_id is None
    assert result.recognition_score == 0.0
    assert result.confidence is RecognitionConfidence.UNKNOWN


def test_wp_amm_trasp_plugin_evidence_is_verbatim() -> None:
    result = PLUGIN.recognize(_observation(_AT_PAGE))
    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert ev.key == "wp_amm_trasp"
    assert ev.matched is True
    assert ev.observed == "post-type-archive-amm_trasp"


def test_wp_amm_trasp_plugin_fingerprint_is_versioned_and_stable() -> None:
    assert PLUGIN.manifest.fingerprint_version == "wordpress-amm-trasp-at-v1"
    a = PLUGIN.recognize(_observation(_AT_PAGE)).fingerprint
    b = PLUGIN.recognize(_observation(_AT_PAGE)).fingerprint
    assert a is not None and a.startswith("sha256:") and a == b


def test_wp_amm_trasp_plugin_handles_incomplete_html() -> None:
    result = PLUGIN.recognize(_observation("<html><body class=post-type-ar"))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_wp_amm_trasp_native_plugin_matches_bridge_on_body_class() -> None:
    observation = _observation(_AT_PAGE)
    native = PLUGIN.recognize(observation)
    legacy = LegacyRecognitionBridge(Surface.TRANSPARENCY).recognize(observation)
    assert native.platform_id == legacy.platform_id == "wp_amm_trasp"
    assert native.recognition_score == legacy.recognition_score
    assert native.confidence is legacy.confidence
