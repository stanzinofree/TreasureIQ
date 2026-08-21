"""The registry→Firma seam used by the BASE dispatch and AT confirmation.

These tests are the coverage the review flagged missing on ``RecognitionMatch``:
they prove the adapter bridges the registry's string ``platform_id`` back onto
the legacy :class:`Piattaforma` enum, synthesises a ``prova``, maps a miss to the
sentinel, and — the Gate 0 guard — refuses SERVICE_PORTAL rather than collapsing
a recognised portal to ``IGNOTA``.
"""

from __future__ import annotations

import pytest

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition_adapter import firma_da_registro
from treasureiq.ingest.piattaforma import Piattaforma, firma_da_risposta

_ENTRYPOINT = "https://comune.example.it/"


def _firma(body: str, *, surface: Surface, headers: dict[str, str] | None = None):
    return firma_da_registro(
        headers=headers or {},
        html=body,
        surface=surface,
        source_id="058003",
        entrypoint_url=_ENTRYPOINT,
    )


def test_base_wordpress_maps_to_enum_with_prova():
    body = '<html><head><link rel="https://api.w.org/" href="/wp-json/"></head>'
    firma = _firma(body, surface=Surface.ORDINARY_DATA)
    assert firma.piattaforma is Piattaforma.WORDPRESS_GENERICO
    assert firma.prova  # synthesised from the winning evidence, never empty


def test_at_urbi_maps_to_enum_with_prova():
    body = '<a href="/portale/ur1UR033.sto?ente=x">Amministrazione Trasparente</a>'
    firma = _firma(body, surface=Surface.TRANSPARENCY)
    assert firma.piattaforma is Piattaforma.URBI
    assert firma.prova


def test_miss_maps_to_ignota_sentinel():
    firma = _firma("<html><body>ignoto</body></html>", surface=Surface.ORDINARY_DATA)
    assert firma.piattaforma is Piattaforma.IGNOTA
    assert firma.prova is None


def test_base_parity_with_classifier_on_non_migrated_family():
    # Drupal is served by the bridge (not retired): the adapter must agree with
    # the shared classifier on the platform enum.
    headers = {"x-drupal-cache": "HIT"}
    body = "<html></html>"
    firma = _firma(body, surface=Surface.ORDINARY_DATA, headers=headers)
    legacy = firma_da_risposta(headers=headers, html=body, includi_at=False)
    assert firma.piattaforma is Piattaforma.DRUPAL
    assert firma.piattaforma == legacy.piattaforma


def test_base_migrated_family_platform_comes_from_native_plugin():
    # ComWeb is retired from the bridge; the enum bridged back must still be the
    # migrated platform, now sourced from the native plugin.
    body = '<meta name="generator" content="ComWeb ePublic 4.2">'
    firma = _firma(body, surface=Surface.ORDINARY_DATA)
    assert firma.piattaforma is Piattaforma.COMWEB


def test_service_portal_is_refused_not_degraded_to_ignota():
    # Gate 0: SP native ids (municipium_portalegen/filodiretto) are not in the
    # enum. The adapter must raise, never hand back a silent IGNOTA.
    with pytest.raises(ValueError, match="SERVICE_PORTAL"):
        firma_da_registro(
            headers={},
            html='<script src="App_Themes/js/siscomJS.js"></script>',
            surface=Surface.SERVICE_PORTAL,
            source_id="058003",
            entrypoint_url=_ENTRYPOINT,
        )
