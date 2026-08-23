from pathlib import Path

from treasureiq import admin_app


def test_admin_overview_is_read_only_and_reports_inventory(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    live_dir = tmp_path / "live"
    data_dir.mkdir()
    (live_dir / "inventario").mkdir(parents=True)
    (live_dir / "inventario" / "058003.json").write_text(
        '{"base_platform":"wordpress_agid","service_portals":[{},{}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(admin_app, "LIVE_DIR", live_dir)
    monkeypatch.setattr(admin_app, "DB_PATH", data_dir / "storico.db")

    result = admin_app.overview()

    assert result["inventories"] == 1
    assert result["service_portal_candidates"] == 2
    assert result["base_platforms"] == {"wordpress_agid": 1}
    assert result["inventory_source_health"] == {
        "reachable": 0, "unreachable": 0, "unknown": 1
    }


def test_admin_unknown_municipality_is_404() -> None:
    from fastapi import HTTPException

    try:
        admin_app.municipality("does-not-exist")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected 404")


def test_admin_overview_counts_low_recognition(tmp_path, monkeypatch) -> None:
    live_dir = tmp_path / "live" / "riconoscimento" / "ordinary_data"
    live_dir.mkdir(parents=True)
    (live_dir / "058003.json").write_text(
        '{"recognition_score":0.7,"coverage_score":0.5}', encoding="utf-8"
    )
    monkeypatch.setattr(admin_app, "LIVE_DIR", tmp_path / "live")
    monkeypatch.setattr(admin_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(admin_app, "DB_PATH", tmp_path / "data" / "storico.db")

    result = admin_app.overview()

    assert result["recognitions"] == 1
    assert result["recognitions_low_score"] == 1
    assert result["coverage_low"] == 1


def test_admin_patterns_exposes_grouped_analytics(tmp_path, monkeypatch) -> None:
    live = tmp_path / "live"
    (live / "inventario").mkdir(parents=True)
    (live / "inventario" / "058003.json").write_text(
        '{"base_platform":"wordpress_agid","service_portals":[{"provider_hint":"urbi","role":"personal_area"}]}',
        encoding="utf-8",
    )
    (live / "riconoscimento" / "ordinary_data").mkdir(parents=True)
    (live / "riconoscimento" / "ordinary_data" / "058003.json").write_text(
        '{"recognition_score":0.95,"coverage_score":0.9,"action":"keep"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_app, "LIVE_DIR", live)
    monkeypatch.setattr(admin_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(admin_app, "DB_PATH", tmp_path / "data" / "storico.db")

    result = admin_app.patterns()

    assert result["service_portal_providers"] == {"urbi": 1}
    assert result["service_portal_roles"] == {"personal_area": 1}
    assert result["service_portal_platforms"] == {
        "urbi": {"entrypoints": 1, "roles": {"personal_area": 1}}
    }
    assert result["recognition_score"] == {"high": 1}
    assert result["recognition_plugins"] == {"unknown": 1}
    assert result["recognition_fingerprint_versions"] == {"unknown": 1}


def test_admin_municipality_search_is_server_side(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_municipalities(*, limit: int, q: str) -> list[dict[str, object]]:
        captured.update(limit=limit, q=q)
        return []

    monkeypatch.setattr(admin_app, "municipalities", fake_municipalities)
    html = admin_app.municipalities_page("Albano Laziale")

    assert captured == {"limit": 500, "q": "Albano Laziale"}
    assert "La ricerca interroga il catalogo lato server" in html
    assert "filterRows" not in html
