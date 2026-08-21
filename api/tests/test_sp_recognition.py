"""Native-only SERVICE_PORTAL recognition seam (`riconosci_service_portal`).

The seam runs the SP registry built with the native plugins ALONE — no legacy
bridge. The load-bearing guardrail: a Municipium *portal* page that carries the
theme container but not the portalegen asset must recognise NOTHING, never the
BASE id ``municipium`` the bridge would mis-claim on that surface.
"""

from __future__ import annotations

from treasureiq.catalog.recognition_adapter import riconosci_service_portal

# portalegen requires BOTH the theme container AND the /portalegen/plugins asset.
_PORTALEGEN = (
    '<div class="container-municipium-agid">'
    '<script src="/portalegen/plugins2/app.js"></script></div>'
)
# Municipium theme container alone — the ambiguous signal, also present on BASE.
_MUNICIPIUM_THEME_ONLY = '<div class="container-municipium-agid">home</div>'
# filodiretto requires the versioned route AND the Siscom vendor asset.
_FILODIRETTO = (
    '<form action="/servizi/filodiretto2/ProcedimentiClient.Aspx">'
    '<script src="/js/siscomJS.js"></script></form>'
)


def _riconosci(html: str, *, entrypoint_url: str = "https://portale.example.it/"):
    return riconosci_service_portal(
        headers={}, html=html, source_id="058003", entrypoint_url=entrypoint_url,
    )


def test_portalegen_recognised_native():
    sp = _riconosci(_PORTALEGEN)
    assert sp.platform_id == "municipium_portalegen"
    assert sp.recognition_score == 0.995
    assert sp.fingerprint
    assert sp.prova


def test_municipium_theme_without_asset_is_none_not_base_municipium():
    # The whole point of the native-only SP registry: no BASE id leaks here.
    sp = _riconosci(_MUNICIPIUM_THEME_ONLY)
    assert sp.platform_id is None
    assert sp.platform_id != "municipium"
    assert sp.recognition_score == 0.0
    assert sp.evidence == ()


def test_filodiretto_recognised_native():
    sp = _riconosci(_FILODIRETTO)
    assert sp.platform_id == "filodiretto"
    assert sp.fingerprint
    assert sp.prova


def test_filodiretto_route_in_entrypoint_url_only():
    # The route recurs in the entrypoint URL; the asset is in the body.
    body = '<script src="/js/siscomJS.js"></script>'
    sp = _riconosci(
        body,
        entrypoint_url="https://servizidigitali.example.it/servizi/filodiretto2/ProcedimentiClient.Aspx",
    )
    assert sp.platform_id == "filodiretto"


def test_generic_html_is_miss():
    sp = _riconosci("<html><body>portale comunale generico</body></html>")
    assert sp.platform_id is None
    assert sp.recognition_score == 0.0
