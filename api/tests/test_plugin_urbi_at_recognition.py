"""T1 native plugin: URBI Amministrazione Trasparente (TRANSPARENCY surface).

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
from treasureiq.plugins.recognition.at.urbi import PLUGIN


def _observation(body: str, **headers: str) -> RecognitionObservation:
    return RecognitionObservation(
        source_id="058003",
        surface=Surface.TRANSPARENCY,
        entrypoint_url="https://comune.example.it/amministrazione-trasparente",
        http_status=200,
        headers=headers,
        body=body,
    )


_AT_PAGE = (
    '<html><head><title>Amministrazione Trasparente</title></head>'
    '<body><a href="/portale/ur1UR033.sto?ente=x">Trasparenza</a></body></html>'
)


def test_urbi_plugin_matches_application_route() -> None:
    result = PLUGIN.recognize(_observation(_AT_PAGE))
    assert result.platform_id == "urbi"
    assert result.confidence is RecognitionConfidence.HIGH
    # (100 - 11*0.1)/100 — definitive, minus the urbi_at table rank.
    assert result.recognition_score == pytest.approx(0.989)


def test_urbi_plugin_ignores_bare_asset_path() -> None:
    # A BASE page that only embeds the portal's Bootstrap style must NOT be
    # claimed: the functional route is required, not a generic /urbi/ asset.
    body = '<html><head><link rel="stylesheet" href="/urbi/css/bootstrap.css"></head></html>'
    result = PLUGIN.recognize(_observation(body))
    assert result.platform_id is None
    assert result.recognition_score == 0.0
    assert result.confidence is RecognitionConfidence.UNKNOWN


def test_urbi_plugin_evidence_is_verbatim() -> None:
    result = PLUGIN.recognize(_observation(_AT_PAGE))
    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert ev.key == "urbi_at"
    assert ev.matched is True
    assert ev.observed == "ur1UR033.sto"


def test_urbi_plugin_fingerprint_is_versioned_and_stable() -> None:
    assert PLUGIN.manifest.fingerprint_version == "urbi-at-v1"
    a = PLUGIN.recognize(_observation(_AT_PAGE)).fingerprint
    b = PLUGIN.recognize(_observation(_AT_PAGE)).fingerprint
    assert a is not None and a.startswith("sha256:") and a == b


def test_urbi_plugin_handles_incomplete_html() -> None:
    # Truncated mid-tag, route absent: no crash, no claim.
    result = PLUGIN.recognize(_observation("<html><head><link rel=styl"))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_urbi_native_plugin_matches_bridge_on_route_signature() -> None:
    observation = _observation(_AT_PAGE)
    native = PLUGIN.recognize(observation)
    legacy = LegacyRecognitionBridge(Surface.TRANSPARENCY).recognize(observation)
    assert native.platform_id == legacy.platform_id == "urbi"
    assert native.recognition_score == legacy.recognition_score
    assert native.confidence is legacy.confidence
