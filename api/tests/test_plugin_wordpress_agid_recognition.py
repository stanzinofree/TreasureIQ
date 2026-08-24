from __future__ import annotations

from pathlib import Path

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


# ── CPT servizi marker — real /wp-json/wp/v2/types payload (Arona) ──────────

_TYPES_FIXTURE = Path(__file__).parent / "fixtures" / "wordpress_agid" / "arona_types.json"


def test_types_fixture_fires_cpt_servizi_marker() -> None:
    # Real bytes captured live from Arona's /wp-json/wp/v2/types: the AgID
    # service CPT is declared ("slug":"servizio" + "rest_base":"servizi").
    result = PLUGIN.recognize(_observation(_TYPES_FIXTURE.read_text("utf-8")))
    # Identity stays the generic WordPress one: the marker strengthens the
    # fingerprint, it does not invent a more specific platform id.
    assert result.platform_id == "wordpress_generico"
    per_key = {e.key: e for e in result.evidence}
    assert "cpt_servizi" in per_key
    # The CPT declaration is the winning (definitive) evidence on this payload:
    # no api.w.org link nor generator meta lives in the types JSON.
    assert per_key["cpt_servizi"].matched is True
    assert "link_wp_api" not in per_key
    assert "generator" not in per_key
    assert result.recognition_score == per_key["cpt_servizi"].weight
    assert result.recognition_score > 0.99
    assert result.fingerprint is not None


def test_rest_dialects_separated_by_item_shape_not_theme() -> None:
    # Same Design Comuni theme, two REST dialects: only the observed item
    # shape separates them.  Real payloads captured live from Arona (A) and
    # Albaredo d'Adige (B).
    fixtures = Path(__file__).parent / "fixtures" / "wordpress_agid"
    dialetto_a = PLUGIN.recognize(
        _observation((fixtures / "arona_carta_identita.json").read_text("utf-8"))
    )
    dialetto_b = PLUGIN.recognize(
        _observation((fixtures / "albaredo_dialettoB_raw.json").read_text("utf-8"))
    )
    keys_a = {e.key for e in dialetto_a.evidence}
    keys_b = {e.key for e in dialetto_b.evidence}
    assert "rest_item_standard" in keys_a
    assert "rest_item_custom" not in keys_a
    assert "rest_item_custom" in keys_b
    assert "rest_item_standard" not in keys_b
    # The two dialect fingerprints must never collapse into one.
    assert dialetto_a.fingerprint != dialetto_b.fingerprint


def test_rest_item_custom_requires_service_cpt_anchor() -> None:
    # "ID"/"post_title" without post_type "servizio" is any custom WP export,
    # not the dialect-B service controller.
    result = PLUGIN.recognize(_observation('[{"ID":1,"post_title":"x"}]'))
    assert all(e.key != "rest_item_custom" for e in result.evidence)


def test_cpt_servizi_marker_requires_both_signals() -> None:
    # "rest_base":"servizi" alone (or the slug alone) is not a CPT declaration.
    solo_rest = PLUGIN.recognize(_observation('{"rest_base":"servizi"}'))
    solo_slug = PLUGIN.recognize(_observation('{"slug":"servizio"}'))
    for result in (solo_rest, solo_slug):
        assert all(e.key != "cpt_servizi" for e in result.evidence)
        assert result.recognition_score == 0.0
