"""T1 native plugin: Siscom Filodiretto (SERVICE_PORTAL surface).

Greenfield fingerprint captured live from Sauze d'Oulx's Filodiretto portal
(servizidigitali.comune.sauzedoulx.to.it/servizi/filodiretto2/ProcedimentiClient.Aspx).
Unlike portalegen the v1 bridge is fully blind — it returns ``ignota`` with no
signature scored — so the plugin fills the gap outright rather than winning a
tie. Obligatory matrix otherwise: match, false positives for each half of the
two-signal AND, verbatim evidence, versioned fingerprint, incomplete HTML,
no network.
"""

from __future__ import annotations

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import RecognitionConfidence
from treasureiq.catalog.recognition_bridge import LegacyRecognitionBridge
from treasureiq.catalog.recognition_plugins import RecognitionObservation
from treasureiq.plugins.recognition.service_portal.filodiretto import PLUGIN


def _observation(body: str, *, entrypoint: str = "https://comune.example.it/") -> RecognitionObservation:
    # Neutral entrypoint by default so the false-positive tests control both
    # halves of the two-signal AND through the body alone.
    return RecognitionObservation(
        source_id="001265",
        surface=Surface.SERVICE_PORTAL,
        entrypoint_url=entrypoint,
        http_status=200,
        headers={"server": "Microsoft-IIS/10.0"},
        body=body,
    )


# Verbatim fragments from the live Sauze d'Oulx Filodiretto page.
_FILODIRETTO_PAGE = (
    "<html><head><title>Filodiretto</title></head>"
    '<body><form id="aspnetForm" action="./ProcedimentiClient.Aspx" method="post">'
    '<input type="hidden" name="__VIEWSTATE" value="/wEPDwUKabc"/>'
    '<script src="App_Themes/js/siscomJS.js"></script>'
    '<script src="assets/bootstrap-italia/dist/js/bootstrap-italia.bundle.min.js"></script>'
    '<script src="/servizi/filodiretto2/ScriptResource.axd"></script>'
    "</form></body></html>"
)


def test_filodiretto_plugin_matches_both_signals() -> None:
    result = PLUGIN.recognize(_observation(_FILODIRETTO_PAGE))
    assert result.platform_id == "filodiretto"
    assert result.confidence is RecognitionConfidence.HIGH
    assert result.recognition_score == 0.995


def test_filodiretto_plugin_matches_route_from_entrypoint_url() -> None:
    # Real pages carry the route in the URL; the vendor asset stays in the body.
    body = '<script src="App_Themes/js/siscomJS.js"></script>'
    entry = "https://servizi.comune.example.it/servizi/filodiretto2/ProcedimentiClient.Aspx"
    result = PLUGIN.recognize(_observation(body, entrypoint=entry))
    assert result.platform_id == "filodiretto"
    assert result.recognition_score == 0.995


def test_filodiretto_plugin_rejects_route_without_vendor_asset() -> None:
    # The product route alone is not enough: the bare word is the discovery hint.
    body = '<script src="/servizi/filodiretto2/ScriptResource.axd"></script>'
    result = PLUGIN.recognize(_observation(body))
    assert result.platform_id is None
    assert result.recognition_score == 0.0
    assert result.confidence is RecognitionConfidence.UNKNOWN


def test_filodiretto_plugin_rejects_vendor_asset_without_route() -> None:
    # A Siscom asset without the Filodiretto route is a different Siscom product.
    body = '<script src="App_Themes/js/siscomJS.js"></script>'
    result = PLUGIN.recognize(_observation(body))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_filodiretto_plugin_evidence_is_verbatim() -> None:
    result = PLUGIN.recognize(_observation(_FILODIRETTO_PAGE))
    keys = {ev.key for ev in result.evidence}
    assert keys == {"filodiretto_route", "siscom_asset"}
    observed = {ev.observed for ev in result.evidence}
    assert "/servizi/filodiretto2/" in observed
    assert "siscomJS.js" in observed
    assert all(ev.matched for ev in result.evidence)


def test_filodiretto_plugin_fingerprint_is_versioned_and_stable() -> None:
    assert PLUGIN.manifest.fingerprint_version == "filodiretto-sp-v1"
    a = PLUGIN.recognize(_observation(_FILODIRETTO_PAGE)).fingerprint
    b = PLUGIN.recognize(_observation(_FILODIRETTO_PAGE)).fingerprint
    assert a is not None and a.startswith("sha256:") and a == b


def test_filodiretto_plugin_handles_incomplete_html() -> None:
    result = PLUGIN.recognize(_observation("<html><head><script src=App_Themes/js/sis"))
    assert result.platform_id is None
    assert result.recognition_score == 0.0


def test_filodiretto_plugin_fills_the_bridge_gap() -> None:
    # The v1 bridge has no Filodiretto/Siscom signature for this markup and
    # returns the empty "ignota" verdict; the native plugin fills the gap.
    observation = _observation(_FILODIRETTO_PAGE)
    native = PLUGIN.recognize(observation)
    legacy = LegacyRecognitionBridge(Surface.SERVICE_PORTAL).recognize(observation)
    assert native.platform_id == "filodiretto"
    assert legacy.platform_id is None
    assert legacy.recognition_score == 0.0
