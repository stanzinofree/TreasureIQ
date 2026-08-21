"""Activation gate for the first native recognition plugin.

The seam and the ``wordpress_agid_base`` plugin are built and pass parity
against the v1 bridge. This file is the review gate the plan makes a
prerequisite: it proves the native plugin wins WordPress BASE inside the
production registry, that non-WordPress surfaces still fall through to the
bridge, and that the agreed BASE policy turns weak-but-genuine WordPress
evidence into an automatic REDISCOVER rather than a human MANUAL_REVIEW.
"""

from __future__ import annotations

from datetime import UTC, datetime

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import RecognitionAction, action_for_recognition
from treasureiq.catalog.recognition_bridge import (
    _RETIRED_TO_NATIVE,
    BASE_RECOGNITION_POLICY,
    LegacyRecognitionBridge,
    build_recognition_registry,
)
from treasureiq.catalog.recognition_plugins import RecognitionObservation
from treasureiq.catalog.recognition_registry import build_recognition_result

_ENTRYPOINT = "https://comune.example.it/"


def _observe(body: str, *, surface: Surface = Surface.ORDINARY_DATA) -> RecognitionObservation:
    return RecognitionObservation(
        source_id="058003",
        surface=surface,
        entrypoint_url=_ENTRYPOINT,
        http_status=200,
        body=body,
    )


def test_native_plugin_owns_wordpress_base_in_production_registry():
    registry = build_recognition_registry()
    body = '<html><head><link rel="https://api.w.org/" href="/wp-json/"></head>'
    match = registry.recognize(_observe(body))
    assert match is not None
    assert match.manifest.plugin_id == "wordpress_agid_base"
    assert match.result.platform_id == "wordpress_generico"


def test_native_urbi_owns_transparency_in_production_registry():
    registry = build_recognition_registry()
    body = '<a href="/portale/ur1UR033.sto?ente=x">Amministrazione Trasparente</a>'
    match = registry.recognize(_observe(body, surface=Surface.TRANSPARENCY))
    assert match is not None
    assert match.manifest.plugin_id == "urbi_at"
    assert match.result.platform_id == "urbi"
    # Same page still classifies through the bridge — the native plugin must
    # win the tie, not lose to the wildcard fallback.
    bridge = LegacyRecognitionBridge(Surface.TRANSPARENCY).recognize(
        _observe(body, surface=Surface.TRANSPARENCY)
    )
    assert match.result.recognition_score == bridge.recognition_score


def test_native_jcitygov_owns_transparency_in_production_registry():
    registry = build_recognition_registry()
    body = (
        '<link rel="stylesheet" '
        'href="https://trasparenza-valutazione-merito.it/x/style.css">'
    )
    match = registry.recognize(_observe(body, surface=Surface.TRANSPARENCY))
    assert match is not None
    assert match.manifest.plugin_id == "jcitygov_at"
    assert match.result.platform_id == "jcitygov"
    bridge = LegacyRecognitionBridge(Surface.TRANSPARENCY).recognize(
        _observe(body, surface=Surface.TRANSPARENCY)
    )
    assert match.result.recognition_score == bridge.recognition_score


def test_native_portalegen_owns_service_portal_in_production_registry():
    registry = build_recognition_registry()
    body = (
        '<link href="/portalegen/plugins2/css/bootstrap-italia-bluwhite.css" rel="stylesheet">'
        '<div class="container-fluid container-municipium-agid"></div>'
    )
    match = registry.recognize(_observe(body, surface=Surface.SERVICE_PORTAL))
    assert match is not None
    assert match.manifest.plugin_id == "municipium_portalegen_sp"
    assert match.result.platform_id == "municipium_portalegen"
    # The bridge mis-claims the generic "municipium" at the same score; the
    # native plugin wins the tie-break and corrects the surface identity.
    bridge = LegacyRecognitionBridge(Surface.SERVICE_PORTAL).recognize(
        _observe(body, surface=Surface.SERVICE_PORTAL)
    )
    assert bridge.platform_id == "municipium"
    assert match.result.recognition_score == bridge.recognition_score


def test_native_filodiretto_owns_service_portal_in_production_registry():
    registry = build_recognition_registry()
    body = (
        '<script src="App_Themes/js/siscomJS.js"></script>'
        '<script src="/servizi/filodiretto2/ScriptResource.axd"></script>'
    )
    match = registry.recognize(_observe(body, surface=Surface.SERVICE_PORTAL))
    assert match is not None
    assert match.manifest.plugin_id == "filodiretto_sp"
    assert match.result.platform_id == "filodiretto"
    # True greenfield: the bridge is blind to this page and returns the empty
    # "ignota" verdict, so the native plugin fills the gap outright.
    bridge = LegacyRecognitionBridge(Surface.SERVICE_PORTAL).recognize(
        _observe(body, surface=Surface.SERVICE_PORTAL)
    )
    assert bridge.platform_id is None
    assert bridge.recognition_score == 0.0


def test_native_comweb_owns_base_in_production_registry():
    registry = build_recognition_registry()
    body = '<meta name="generator" content="ComWeb ePublic 4.2">'
    match = registry.recognize(_observe(body, surface=Surface.ORDINARY_DATA))
    assert match is not None
    assert match.manifest.plugin_id == "comweb_base"
    assert match.result.platform_id == "comweb"
    bridge = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(
        _observe(body, surface=Surface.ORDINARY_DATA)
    )
    assert match.result.recognition_score == bridge.recognition_score


def test_native_wp_amm_trasp_owns_transparency_in_production_registry():
    registry = build_recognition_registry()
    body = '<body class="post-type-archive-amm_trasp"></body>'
    match = registry.recognize(_observe(body, surface=Surface.TRANSPARENCY))
    assert match is not None
    assert match.manifest.plugin_id == "wordpress_amm_trasp_at"
    assert match.result.platform_id == "wp_amm_trasp"
    bridge = LegacyRecognitionBridge(Surface.TRANSPARENCY).recognize(
        _observe(body, surface=Surface.TRANSPARENCY)
    )
    assert match.result.recognition_score == bridge.recognition_score


def test_bridge_still_wins_non_wordpress_surface():
    registry = build_recognition_registry()
    # A Drupal header the native WordPress plugin cannot claim: the bridge must
    # remain the fallback and win.
    observation = RecognitionObservation(
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        entrypoint_url=_ENTRYPOINT,
        http_status=200,
        headers={"x-drupal-cache": "HIT"},
        body="<html></html>",
    )
    match = registry.recognize(observation)
    assert match is not None
    assert match.manifest.plugin_id == "legacy_bridge_ordinary_data"
    assert match.result.platform_id == "drupal"


# Passo C — one bridge-matching fixture per migrated family: (surface, body, platform).
_MIGRATED_FIXTURES = [
    (Surface.ORDINARY_DATA, '<meta name="generator" content="WordPress 6.5">', "wordpress_generico"),
    (Surface.ORDINARY_DATA, '<meta name="generator" content="ComWeb ePublic 4.2">', "comweb"),
    (Surface.TRANSPARENCY, '<a href="/portale/ur1UR033.sto?ente=x">AT</a>', "urbi"),
    (
        Surface.TRANSPARENCY,
        '<link href="https://trasparenza-valutazione-merito.it/x/s.css">',
        "jcitygov",
    ),
    (Surface.TRANSPARENCY, '<body class="post-type-archive-amm_trasp">', "wp_amm_trasp"),
]


def test_passo_c_retired_bridge_drops_migrated_but_default_still_classifies():
    """The production bridge stops claiming migrated families; the bare bridge
    (the shared classifier path used by censimento/discovery/confirmation) is
    untouched and still detects them."""
    for surface, body, platform in _MIGRATED_FIXTURES:
        obs = _observe(body, surface=surface)
        assert platform in _RETIRED_TO_NATIVE
        default = LegacyRecognitionBridge(surface).recognize(obs)
        retired = LegacyRecognitionBridge(surface, retired=_RETIRED_TO_NATIVE).recognize(obs)
        # Shared classifier still detects the platform — the 4 non-recognition
        # consumers keep working.
        assert default.platform_id == platform
        # Production bridge suppresses it: the native plugin is sole authority.
        assert retired.platform_id is None
        assert retired.recognition_score == 0.0


def test_unknown_surface_recognises_nothing_not_a_native_plugin():
    """Regression: an all-miss surface must return None, never an empty result
    falsely attributed to the first native plugin the tie-break reaches."""
    registry = build_recognition_registry()
    for surface in (Surface.ORDINARY_DATA, Surface.TRANSPARENCY, Surface.SERVICE_PORTAL):
        match = registry.recognize(_observe("<html><body>ignoto</body></html>", surface=surface))
        assert match is None


def test_passo_c_retired_bridge_still_serves_unmigrated_family():
    """Retirement is scoped to migrated platforms only; everything else still
    falls through to the bridge."""
    observation = RecognitionObservation(
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        entrypoint_url=_ENTRYPOINT,
        http_status=200,
        headers={"x-drupal-cache": "HIT"},
        body="<html></html>",
    )
    retired = LegacyRecognitionBridge(
        Surface.ORDINARY_DATA, retired=_RETIRED_TO_NATIVE
    ).recognize(observation)
    assert retired.platform_id == "drupal"
    assert "drupal" not in _RETIRED_TO_NATIVE


def test_base_policy_matrix_matches_agreed_thresholds():
    """rest→KEEP, heuristic-only→REDISCOVER, empty→MANUAL_REVIEW."""
    registry = build_recognition_registry()
    checked_at = datetime(2026, 8, 21, tzinfo=UTC)

    rest = registry.recognize(_observe('<link rel="https://api.w.org/" href="/wp-json/">'))
    heuristic = registry.recognize(_observe('<link rel="stylesheet" href="/wp-content/x.css">'))
    empty = registry.recognize(_observe("<html><body>Comune</body></html>"))
    assert rest is not None and heuristic is not None
    # Nothing recognises an empty page: the registry returns None rather than an
    # empty native attribution. None is the caller's manual-review signal.
    assert empty is None

    def action(match):
        return build_recognition_result(
            _observe(""), match, checked_at=checked_at, policy=BASE_RECOGNITION_POLICY
        ).action

    assert action(rest) is RecognitionAction.KEEP
    assert action(heuristic) is RecognitionAction.REDISCOVER
    # Guard the boundary directly: 0.49 must not fall into manual review.
    assert (
        action_for_recognition(score=0.49, policy=BASE_RECOGNITION_POLICY)
        is RecognitionAction.REDISCOVER
    )


def test_native_plugin_matches_bridge_on_generator_signature():
    """Parity gap the plugin's own suite left untested: the generator signal."""
    body = '<meta name="generator" content="WordPress 6.5">'
    native = build_recognition_registry().recognize(_observe(body))
    bridge = LegacyRecognitionBridge(Surface.ORDINARY_DATA).recognize(_observe(body))
    assert native is not None
    assert native.result.platform_id == bridge.platform_id == "wordpress_generico"
    assert native.result.recognition_score == bridge.recognition_score


def test_native_fingerprint_is_deterministic_and_signal_scoped():
    from treasureiq.plugins.recognition.base import WORDPRESS_AGID_RECOGNITION_PLUGIN as plugin

    rest = '<link rel="https://api.w.org/" href="/wp-json/">'
    asset = '<link rel="stylesheet" href="/wp-content/x.css">'
    first = plugin.recognize(_observe(rest)).fingerprint
    second = plugin.recognize(_observe(rest)).fingerprint
    assert first is not None and first == second
    # Different matched signals must yield a different fingerprint.
    assert plugin.recognize(_observe(asset)).fingerprint != first
