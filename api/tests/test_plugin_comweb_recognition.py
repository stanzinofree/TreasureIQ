"""T1 native plugin: ComWeb (BASE / ORDINARY_DATA surface).

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
from treasureiq.plugins.recognition.base.comweb import PLUGIN


def _observation(body: str, **headers: str) -> RecognitionObservation:
    return RecognitionObservation(
        source_id="099999",
        surface=Surface.ORDINARY_DATA,
        entrypoint_url="https://comune.example.it/",
        http_status=200,
        headers=headers,
        body=body,
    )


_COMWEB_PAGE = (
    '<html><head><meta name="generator" content="ComWeb ePublic 4.2"></head>'
    "<body>Comune</body></html>"
)


def test_comweb_plugin_matches_generator() -> None:
    result = PLUGIN.recognize(_observation(_COMWEB_PAGE))
    assert result.platform_id == "comweb"
    assert result.confidence is RecognitionConfidence.HIGH
    # (100 - 2*0.1)/100 — definitive generator, minus the generator table rank.
    assert result.recognition_score == pytest.approx(0.998)


def test_comweb_plugin_ignores_other_generator() -> None:
    body = '<html><head><meta name="generator" content="WordPress 6.5"></head></html>'
    result = PLUGIN.recognize(_observation(body))
    assert result.platform_id is None
    assert result.recognition_score == 0.0
    assert result.confidence is RecognitionConfidence.UNKNOWN


def test_comweb_plugin_evidence_is_verbatim() -> None:
    result = PLUGIN.recognize(_observation(_COMWEB_PAGE))
    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert ev.key == "generator"
    assert ev.matched is True
    assert ev.observed == "ComWeb ePublic 4.2"


def test_comweb_plugin_fingerprint_is_versioned_and_stable() -> None:
    assert PLUGIN.manifest.fingerprint_version == "comweb-base-v1"
    a = PLUGIN.recognize(_observation(_COMWEB_PAGE)).fingerprint
    b = PLUGIN.recognize(_observation(_COMWEB_PAGE)).fingerprint
    assert a is not None and a.startswith("sha256:") and a == b


def test_comweb_plugin_handles_incomplete_html() -> None:
    result = PLUGIN.recognize(_observation("<html><head><meta name=gener"))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_comweb_native_plugin_matches_bridge_on_generator_signature() -> None:
    observation = _observation(_COMWEB_PAGE)
    native = PLUGIN.recognize(observation)
    legacy = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(observation)
    assert native.platform_id == legacy.platform_id == "comweb"
    assert native.recognition_score == legacy.recognition_score
    assert native.confidence is legacy.confidence
