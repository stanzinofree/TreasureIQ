from datetime import datetime, timezone

from treasureiq.catalog import inventory_discovery
from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition_adapter import firma_da_registro
from treasureiq.ingest.piattaforma import classifica_risposta


def test_inventory_discovery_does_not_require_a_data_connector(tmp_path, monkeypatch):
    monkeypatch.setattr(
        inventory_discovery,
        "fetch_guardato",
        lambda *args, **kwargs: ({}, b'<a href="/servizi-online">Servizi online</a>', "https://comune.test/"),
    )
    monkeypatch.setattr(
        inventory_discovery,
        "scopri_pagina_at",
        lambda **kwargs: type("At", (), {"at_url": None, "piattaforma_at": type("P", (), {"value": "non_trovata"})()})(),
    )
    result = inventory_discovery.discover_source_inventory(
        live_dir=tmp_path,
        source_id="000001",
        base_url="https://comune.test/",
    )
    assert result is not None
    assert result.source_id == "000001"
    assert result.service_portals[0].role.value == "online_service"


# M1 characterization (Fase 1 strangler): `discover_source_inventory` used to
# call `firma_da_risposta(...).vincitore` directly; it now goes through the
# registry seam `firma_da_registro`. These fixtures pin that the BASE platform
# `discover_source_inventory` ends up persisting is the SAME one the legacy
# classifier would have picked on the identical (headers, html) pair — proof
# the migration didn't silently change what a comune gets recognised as.
_WORDPRESS_AGID_HOME = (
    '<html><head><link rel="https://api.w.org/" href="https://comune.test/wp-json/"></head>'
    "<body>Comune di Test</body></html>"
)
_COMWEB_HOME = '<html><head><meta name="generator" content="ComWeb ePublic 4.2"></head></html>'


def _run_discovery_through_seam(tmp_path, monkeypatch, *, headers: dict[str, str], html: str):
    monkeypatch.setattr(
        inventory_discovery,
        "fetch_guardato",
        lambda *args, **kwargs: (headers, html.encode("utf-8"), "https://comune.test/"),
    )
    monkeypatch.setattr(
        inventory_discovery,
        "scopri_pagina_at",
        lambda **kwargs: type(
            "At", (), {"at_url": None, "piattaforma_at": type("P", (), {"value": "non_trovata"})()}
        )(),
    )
    return inventory_discovery.discover_source_inventory(
        live_dir=tmp_path,
        source_id="058003",
        base_url="https://comune.test/",
    )


def test_m1_base_platform_matches_legacy_classifier_on_wordpress_agid(tmp_path, monkeypatch):
    result = _run_discovery_through_seam(
        tmp_path, monkeypatch, headers={}, html=_WORDPRESS_AGID_HOME
    )
    legacy = classifica_risposta(headers={}, html=_WORDPRESS_AGID_HOME, includi_at=False).vincitore
    assert result.base_platform == legacy.piattaforma.value

    # Same input through the seam directly, for good measure: it must agree
    # with what discover_source_inventory persisted.
    seam = firma_da_registro(
        headers={}, html=_WORDPRESS_AGID_HOME, surface=Surface.ORDINARY_DATA,
        source_id="058003", entrypoint_url="https://comune.test/",
    )
    assert result.base_platform == seam.piattaforma.value


def test_m1_base_platform_matches_legacy_classifier_on_comweb(tmp_path, monkeypatch):
    result = _run_discovery_through_seam(tmp_path, monkeypatch, headers={}, html=_COMWEB_HOME)
    legacy = classifica_risposta(headers={}, html=_COMWEB_HOME, includi_at=False).vincitore
    assert result.base_platform == legacy.piattaforma.value
