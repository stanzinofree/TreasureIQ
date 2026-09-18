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


def test_refresh_batch_chiama_refresh_dati_in_process(monkeypatch, tmp_path):
    # Il refresh gira in-process (come confirmation), un comune alla volta via
    # refresh_dati_connettore — non più shell-out a registro_cli.
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="refresh", delay=0, refresh_interval_seconds=60
    )
    chiamati = []

    class _Esito:
        piattaforma = "municipium"
        letto_il = "2026-01-01T00:00:00+00:00"

    def fake_refresh(codice, **kwargs):
        chiamati.append(codice)
        return _Esito()

    monkeypatch.setattr(sweep_worker, "refresh_dati_connettore", fake_refresh)

    assert sweep_worker.run_batch(config, ["001", "002"]) == 0
    assert chiamati == ["001", "002"]


def test_refresh_batch_un_errore_non_ferma_il_lotto(monkeypatch, tmp_path):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="refresh", delay=0, refresh_interval_seconds=60
    )
    visti = []

    def fake_refresh(codice, **kwargs):
        visti.append(codice)
        if codice == "001":
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(sweep_worker, "refresh_dati_connettore", fake_refresh)

    # Un comune fallito → exit 1, ma il lotto prosegue su tutti.
    assert sweep_worker.run_batch(config, ["001", "002"]) == 1
    assert visti == ["001", "002"]


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

    def fake_confirmation(*, live_dir, source_id, dry_run=False, esecutore=None):
        chiamata["live_dir"] = live_dir
        chiamata["source_id"] = source_id
        return ()

    monkeypatch.setattr(sweep_worker, "confirm_inventory", fake_confirmation)

    assert sweep_worker.run_batch(config, ["001"]) == 0
    assert chiamata["source_id"] == "001"
    assert chiamata["live_dir"] == sweep_worker.LIVE_DIR


def test_config_from_env_modalita_invalida_ricade_su_refresh(monkeypatch):
    # Una modalità sconosciuta non deve impostare silenziosamente confirmation:
    # il fallback coincide col log ("uso refresh") ed è il default dichiarato.
    monkeypatch.setenv("TREASUREIQ_SWEEP_MODE", "banana")
    config = sweep_worker.config_from_env()
    assert config.mode == "refresh"


def test_config_from_env_legge_pace_dominio(monkeypatch):
    monkeypatch.setenv("TREASUREIQ_SWEEP_PACE_S", "1.5")
    assert sweep_worker.config_from_env().pace_dominio_s == 1.5


def test_config_from_env_pace_dominio_default(monkeypatch):
    monkeypatch.delenv("TREASUREIQ_SWEEP_PACE_S", raising=False)
    assert sweep_worker.config_from_env().pace_dominio_s == 0.5


def test_refresh_batch_attiva_il_pacer_per_comune(monkeypatch, tmp_path):
    # Il refresh scopa la raffica 429 attivando un PacerDominio per ogni comune;
    # refresh_dati_connettore lo vede via ContextVar, e resta ripristinato dopo.
    from treasureiq.ingest.fetch_pacing import pacer_attivo

    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="refresh", delay=0, pace_dominio_s=0.5
    )
    visti = []

    def fake_refresh(codice, **kwargs):
        visti.append((codice, pacer_attivo() is not None))
        return None

    monkeypatch.setattr(sweep_worker, "refresh_dati_connettore", fake_refresh)

    assert sweep_worker.run_batch(config, ["001", "002"]) == 0
    assert visti == [("001", True), ("002", True)]
    assert pacer_attivo() is None  # ripristinato a fine lotto


def test_refresh_batch_pace_zero_niente_pacer(monkeypatch, tmp_path):
    # pace_dominio_s=0 disattiva il pacing: nessun pacer installato.
    from treasureiq.ingest.fetch_pacing import pacer_attivo

    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="refresh", delay=0, pace_dominio_s=0.0
    )
    visti = []
    monkeypatch.setattr(
        sweep_worker,
        "refresh_dati_connettore",
        lambda codice, **k: visti.append(pacer_attivo()) or None,
    )

    assert sweep_worker.run_batch(config, ["001"]) == 0
    assert visti == [None]
