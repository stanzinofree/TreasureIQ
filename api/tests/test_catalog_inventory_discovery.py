from datetime import datetime, timezone

from treasureiq.catalog import inventory_discovery


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
