"""T1 native plugin: jcitygov Amministrazione Trasparente (TRANSPARENCY surface).

Obligatory matrix (framework-plugin-riconoscimenti.md): positive match, false
positive, score/confidence, verbatim evidence, incomplete HTML, no network,
fingerprint version. Plus parity with the v1 bridge on the same fixture.
"""

from __future__ import annotations

import pytest

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import RecognitionConfidence
from treasureiq.catalog.recognition_bridge import LegacyRecognitionBridge
from treasureiq.catalog.recognition_plugins import RecognitionObservation
from treasureiq.plugins.recognition.at.jcitygov import PLUGIN


def _observation(body: str, **headers: str) -> RecognitionObservation:
    return RecognitionObservation(
        source_id="004072",
        surface=Surface.TRANSPARENCY,
        entrypoint_url="https://comune.example.it/amministrazione-trasparente",
        http_status=200,
        headers=headers,
        body=body,
    )


_AT_PAGE = (
    '<html><head><title>Amministrazione Trasparente</title>'
    '<link rel="stylesheet" href="https://trasparenza-valutazione-merito.it/x/style.css">'
    '</head><body>Trasparenza</body></html>'
)


def test_jcitygov_plugin_matches_vendor_host() -> None:
    result = PLUGIN.recognize(_observation(_AT_PAGE))
    assert result.platform_id == "jcitygov"
    assert result.confidence is RecognitionConfidence.HIGH
    # (100 - 5*0.1)/100 — definitive, minus the host_prodotto table rank.
    assert result.recognition_score == pytest.approx(0.995)


def test_jcitygov_plugin_ignores_plain_at_page() -> None:
    body = '<html><head><title>Amministrazione Trasparente</title></head></html>'
    result = PLUGIN.recognize(_observation(body))
    assert result.platform_id is None
    assert result.recognition_score == 0.0
    assert result.confidence is RecognitionConfidence.UNKNOWN


def test_jcitygov_plugin_evidence_is_verbatim() -> None:
    result = PLUGIN.recognize(_observation(_AT_PAGE))
    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert ev.key == "host_prodotto"
    assert ev.matched is True
    assert ev.observed == "trasparenza-valutazione-merito.it"


def test_jcitygov_plugin_fingerprint_is_versioned_and_stable() -> None:
    assert PLUGIN.manifest.fingerprint_version == "jcitygov-at-v1"
    a = PLUGIN.recognize(_observation(_AT_PAGE)).fingerprint
    b = PLUGIN.recognize(_observation(_AT_PAGE)).fingerprint
    assert a is not None and a.startswith("sha256:") and a == b


def test_jcitygov_plugin_handles_incomplete_html() -> None:
    result = PLUGIN.recognize(_observation("<html><head><link rel=styl"))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_jcitygov_native_plugin_matches_bridge_on_host_signature() -> None:
    observation = _observation(_AT_PAGE)
    native = PLUGIN.recognize(observation)
    legacy = LegacyRecognitionBridge(Surface.TRANSPARENCY).recognize(observation)
    assert native.platform_id == legacy.platform_id == "jcitygov"
    assert native.recognition_score == legacy.recognition_score
    assert native.confidence is legacy.confidence
