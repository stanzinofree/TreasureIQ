from treasureiq import sweep_worker


def test_next_batch_esclude_i_comuni_gia_misurati(monkeypatch, tmp_path):
    config = sweep_worker.WorkerConfig(db=tmp_path / "storico.db", batch_size=2)
    monkeypatch.setattr(sweep_worker, "_comuni_da_censimento", lambda db: ["001", "002", "003"])
    monkeypatch.setattr(
        sweep_worker,
        "_gia_registrati",
        lambda db, giorno: {"001"},
    )

    assert sweep_worker.next_batch(config) == ["002", "003"]


def test_run_batch_delega_al_cli(monkeypatch, tmp_path):
    config = sweep_worker.WorkerConfig(db=tmp_path / "storico.db", lavoratori=4, delay=0)
    chiamata = {}
    def fake_main(argv):
        chiamata["argv"] = argv
        return 0

    monkeypatch.setattr(sweep_worker, "sweep_main", fake_main)

    assert sweep_worker.run_batch(config, ["001", "002"]) == 0
    assert chiamata["argv"][:3] == ["sweep", "001", "002"]
    assert "--lavoratori" in chiamata["argv"]
