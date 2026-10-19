import json
from datetime import datetime, timezone

import pytest

from treasureiq import sweep_worker


def test_refresh_idle_aggiorna_heartbeat_e_conserva_ultimo_batch(monkeypatch, tmp_path):
    monkeypatch.setattr(sweep_worker, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(sweep_worker, "next_batch", lambda config: [])
    stato = tmp_path / "_worker_status.json"
    stato.write_text(json.dumps({
        "aggiornato_il": "2020-01-01T00:00:00+00:00",
        "ultimo_batch": {"riusciti": 3},
    }))

    def ferma_dopo_heartbeat(seconds):
        raise StopIteration

    monkeypatch.setattr(sweep_worker.time, "sleep", ferma_dopo_heartbeat)
    with pytest.raises(StopIteration):
        sweep_worker.run(
            sweep_worker.WorkerConfig(db=tmp_path / "storico.db", mode="refresh")
        )

    aggiornato = json.loads(stato.read_text())
    assert aggiornato["ultimo_batch"] == {"riusciti": 3}
    assert aggiornato["modo"] == "refresh"
    assert datetime.fromisoformat(aggiornato["aggiornato_il"]) > datetime(
        2020, 1, 1, tzinfo=timezone.utc
    )


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


def test_refresh_non_rimette_in_coda_una_lettura_recente(monkeypatch, tmp_path):
    monkeypatch.setattr(sweep_worker, "_comuni_da_censimento", lambda db: ["001"])

    class Cache:
        piattaforma = "municipium"
        controllato_il = "2020-01-01T00:00:00+00:00"
        letto_il = "9999-01-01T00:00:00+00:00"

    monkeypatch.setattr(sweep_worker, "_connettore_cache", lambda codice: Cache())
    config = sweep_worker.WorkerConfig(db=tmp_path / "storico.db", mode="refresh")
    assert sweep_worker.next_batch(config) == []
    assert sweep_worker.next_batch(
        sweep_worker.WorkerConfig(db=config.db, mode="confirmation")
    ) == ["001"]


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


def test_esiti_bootstrap_rimandano_per_esito(tmp_path):
    from datetime import timedelta

    from treasureiq import bootstrap_esiti

    ora = datetime(2026, 10, 19, tzinfo=timezone.utc)
    bootstrap_esiti.registra(tmp_path, "001", "vuoto", "001 X — vuoto", ora)
    bootstrap_esiti.registra(tmp_path, "002", "errore", "002 Y — errore", ora)
    bootstrap_esiti.registra(tmp_path, "003", "ok", "003 Z — ok", ora)
    bootstrap_esiti.registra(tmp_path, "001", "vuoto", "001 X — vuoto", ora)

    esiti = bootstrap_esiti.carica(tmp_path)
    assert esiti["001"]["tentativi"] == 2
    assert esiti["003"]["prossimo_il"] is None
    assert bootstrap_esiti.in_attesa(esiti, ora) == {"001", "002"}
    assert bootstrap_esiti.in_attesa(esiti, ora + timedelta(days=2)) == {"001"}
    assert bootstrap_esiti.in_attesa(esiti, ora + timedelta(days=15)) == set()


def test_prossimi_da_inizializzare_salta_store_attese_e_backoff(monkeypatch, tmp_path):
    from treasureiq import bootstrap_esiti

    monkeypatch.setattr(sweep_worker, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(sweep_worker, "_comuni_da_censimento", lambda db: ["a", "b", "c", "d", "e"])
    monkeypatch.setattr(sweep_worker, "_connettore_inizializzati", lambda: {"a"})
    monkeypatch.setattr(sweep_worker, "_backoff_rete_attivi", lambda ora: {"b"})
    monkeypatch.setattr(
        sweep_worker.bootstrap_sel, "mappa_censimento",
        lambda db: dict.fromkeys("abcde", "comweb"),
    )
    bootstrap_esiti.registra(tmp_path, "c", "vuoto", "c — vuoto")

    config = sweep_worker.WorkerConfig(db=tmp_path / "storico.db", batch_size=1)
    assert sweep_worker.prossimi_da_inizializzare(config) == ["d"]

    monkeypatch.setattr(
        sweep_worker.bootstrap_sel, "mappa_censimento",
        lambda db: {**dict.fromkeys("abce", "comweb"), "d": "magnolia"},
    )
    in_pausa = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", batch_size=1, piattaforme_in_pausa=frozenset({"magnolia"})
    )
    assert sweep_worker.prossimi_da_inizializzare(in_pausa) == ["e"]


def test_run_con_bootstrap_registra_esiti_e_conserva_refresh(monkeypatch, tmp_path):
    from treasureiq import bootstrap_esiti

    monkeypatch.setattr(sweep_worker, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(sweep_worker, "prossimi_da_inizializzare", lambda config: ["x", "y"])
    monkeypatch.setattr(sweep_worker, "next_batch", lambda config: [])
    esiti = {"x": ("ok", "x — ok"), "y": ("rete_non_raggiungibile", "y — rete")}
    monkeypatch.setattr(sweep_worker, "_scansiona_uno", lambda codice: esiti[codice])
    (tmp_path / "_worker_status.json").write_text(json.dumps({"ultimo_batch": {"riusciti": 3}}))

    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="refresh", bootstrap=True, once=True
    )
    assert sweep_worker.run(config) == 0

    stato = json.loads((tmp_path / "_worker_status.json").read_text())
    assert stato["ultimo_batch"] == {"riusciti": 3}
    assert stato["ultimo_bootstrap"]["ok"] == 1
    assert stato["ultimo_bootstrap"]["rete_non_raggiungibile"] == 1
    assert bootstrap_esiti.in_attesa(bootstrap_esiti.carica(tmp_path)) == {"y"}
