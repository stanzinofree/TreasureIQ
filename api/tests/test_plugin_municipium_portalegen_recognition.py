"""T1 native plugin: Municipium portalegen (SERVICE_PORTAL surface).

Greenfield fingerprint captured live from Almese's school-services portal
(serviziscolastici.comune.almese.to.it/portalegen). The v1 bridge has no
portalegen signature, so instead of a parity test we assert the plugin fills a
gap the bridge misses. Obligatory matrix otherwise: match, false positives for
each half of the two-signal AND, verbatim evidence, versioned fingerprint,
incomplete HTML, no network.
"""

from __future__ import annotations

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import RecognitionConfidence
from treasureiq.catalog.recognition_bridge import LegacyRecognitionBridge
from treasureiq.catalog.recognition_plugins import RecognitionObservation
from treasureiq.plugins.recognition.service_portal.municipium_portalegen import PLUGIN


def _observation(body: str, **headers: str) -> RecognitionObservation:
    return RecognitionObservation(
        source_id="001007",
        surface=Surface.SERVICE_PORTAL,
        entrypoint_url="https://serviziscolastici.comune.example.it/portalegen",
        http_status=200,
        headers=headers,
        body=body,
    )


# Verbatim fragments from the live Almese portalegen page.
_PORTALEGEN_PAGE = (
    "<html><head>"
    '<link href="/portalegen/plugins/jquery-ui/jquery-ui.css" rel="stylesheet">'
    '<link href="/portalegen/plugins2/css/bootstrap-italia-bluwhite.css" rel="stylesheet">'
    "</head><body>"
    '<div class="container-fluid container-municipium-agid"><div class="row"></div></div>'
    "</body></html>"
)


def test_portalegen_plugin_matches_both_signals() -> None:
    result = PLUGIN.recognize(_observation(_PORTALEGEN_PAGE))
    assert result.platform_id == "municipium_portalegen"
    assert result.confidence is RecognitionConfidence.HIGH
    # Mirrors the bridge's coincidental municipium host score so the registry
    # tie-break, not the number, decides ownership of the SP surface.
    assert result.recognition_score == 0.995


def test_portalegen_plugin_rejects_theme_without_portal_assets() -> None:
    # BASE Municipium page: has the AGID theme container but no /portalegen tree.
    body = '<div class="container-fluid container-municipium-agid"></div>'
    result = PLUGIN.recognize(_observation(body))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_portalegen_plugin_rejects_assets_without_theme() -> None:
    # A /portalegen path without the Municipium theme is not enough.
    body = '<link href="/portalegen/plugins/x/y.css" rel="stylesheet">'
    result = PLUGIN.recognize(_observation(body))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_portalegen_plugin_evidence_is_verbatim() -> None:
    result = PLUGIN.recognize(_observation(_PORTALEGEN_PAGE))
    keys = {ev.key for ev in result.evidence}
    assert keys == {"municipium_agid", "portalegen_asset"}
    observed = {ev.observed for ev in result.evidence}
    assert "container-municipium-agid" in observed
    assert "/portalegen/plugins/" in observed
    assert all(ev.matched for ev in result.evidence)


def test_portalegen_plugin_fingerprint_is_versioned_and_stable() -> None:
    assert PLUGIN.manifest.fingerprint_version == "municipium-portalegen-sp-v1"
    a = PLUGIN.recognize(_observation(_PORTALEGEN_PAGE)).fingerprint
    b = PLUGIN.recognize(_observation(_PORTALEGEN_PAGE)).fingerprint
    assert a is not None and a.startswith("sha256:") and a == b


def test_portalegen_plugin_handles_incomplete_html() -> None:
    result = PLUGIN.recognize(_observation("<html><head><link href=/porta"))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_portalegen_plugin_corrects_the_bridge_misidentification() -> None:
    # The bridge has no portalegen signature; the word "municipium" in the
    # theme class trips its \bmunicipium\b host rule, so it mis-claims the
    # generic BASE platform. The native plugin claims the specific SP identity
    # at the same score, so the registry tie-break promotes it.
    observation = _observation(_PORTALEGEN_PAGE)
    native = PLUGIN.recognize(observation)
    legacy = LegacyRecognitionBridge(Surface.SERVICE_PORTAL).recognize(observation)
    assert native.platform_id == "municipium_portalegen"
    assert legacy.platform_id == "municipium"
    assert native.recognition_score == legacy.recognition_score
