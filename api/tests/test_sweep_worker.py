from treasureiq import sweep_worker


def test_next_batch_esclude_i_comuni_gia_misurati(monkeypatch, tmp_path):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", batch_size=2, mode="discovery"
    )
    monkeypatch.setattr(sweep_worker, "_comuni_da_censimento", lambda db: ["001", "002", "003"])
    monkeypatch.setattr(
        sweep_worker,
        "_gia_registrati",
        lambda db, giorno: {"001"},
    )

    assert sweep_worker.next_batch(config) == ["002", "003"]


def test_discovery_batch_aggiorna_solo_inventario(monkeypatch, tmp_path):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", lavoratori=4, delay=0, mode="discovery"
    )
    chiamate = []
    monkeypatch.setattr(sweep_worker, "comune_per_codice", lambda codice: type("C", (), {"sito": "https://example.test"})())
    monkeypatch.setattr(
        sweep_worker,
        "discover_source_inventory",
        lambda **kwargs: chiamate.append(kwargs) or type("I", (), {"base_platform": "wp", "transparency_platform": "urbi", "service_portals": ()})(),
    )

    assert sweep_worker.run_batch(config, ["001", "002"]) == 0
    assert [item["source_id"] for item in chiamate] == ["001", "002"]


def test_refresh_batch_usa_il_probe_della_fonte(monkeypatch, tmp_path):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="refresh", delay=0, refresh_interval_seconds=60
    )
    chiamata = {}

    def fake_main(argv):
        chiamata["argv"] = argv
        return 0

    monkeypatch.setattr(sweep_worker, "sweep_main", fake_main)

    assert sweep_worker.run_batch(config, ["001"]) == 0
    assert chiamata["argv"][:3] == ["scan", "001", "--db"]
    assert "--refresh-dati" in chiamata["argv"]
    assert "--lavoratori" not in chiamata["argv"]


def test_refresh_non_promuove_un_comune_senza_cache_a_discovery(monkeypatch, tmp_path):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="refresh", batch_size=2, refresh_interval_seconds=60
    )
    monkeypatch.setattr(sweep_worker, "_comuni_da_censimento", lambda db: ["001", "002"])
    monkeypatch.setattr(sweep_worker, "_connettore_cache", lambda codice: None)

    assert sweep_worker.next_batch(config) == []


def test_confirmation_usa_la_scadenza_quindicinale_del_contratto(
    monkeypatch, tmp_path
):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db",
        mode="confirmation",
        batch_size=2,
        confirmation_interval_seconds=60,
    )
    monkeypatch.setattr(sweep_worker, "_comuni_da_censimento", lambda db: ["001", "002"])

    class Cache:
        controllato_il = "2020-01-01T00:00:00+00:00"
        letto_il = "2020-01-01T00:00:00+00:00"

    monkeypatch.setattr(sweep_worker, "_connettore_cache", lambda codice: Cache())

    assert sweep_worker.next_batch(config) == ["001", "002"]


def test_confirmation_usa_solo_entrypoint_persistiti(monkeypatch, tmp_path):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="confirmation", delay=0
    )
    chiamata = {}

    def fake_confirmation(*, live_dir, source_id, dry_run=False):
        chiamata["live_dir"] = live_dir
        chiamata["source_id"] = source_id
        return ()

    monkeypatch.setattr(sweep_worker, "confirm_inventory", fake_confirmation)

    assert sweep_worker.run_batch(config, ["001"]) == 0
    assert chiamata["source_id"] == "001"
    assert chiamata["live_dir"] == sweep_worker.LIVE_DIR
