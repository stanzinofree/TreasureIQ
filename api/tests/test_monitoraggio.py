"""Tests for the operational monitoring builder (`treasureiq.monitoraggio`).

Covers what the dashboard PR must guarantee: counts coherent with real files,
the coverage/eligibility arithmetic, the demo layer never driving the refresh
worker's state, and the worker state handled when the sidecar is absent, stale
or fresh. All fixtures are tiny on-disk trees so the assertions are exact.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from treasureiq.monitoraggio import build_monitoraggio

CURATED = "nazionale_curated.json"


def _scrivi(percorso: Path, payload: object) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")


def _catalog_file(dir_: Path, codice: str, piattaforma: str) -> None:
    _scrivi(
        dir_ / f"{codice}.json",
        {
            "municipality": codice,
            "services": {
                "s1": {"provider_platform": piattaforma, "source_url": "https://x/s1"},
                "s2": {"provider_platform": piattaforma, "source_url": "https://x/s2"},
            },
        },
    )


def _connettore(dir_: Path, codice: str, controllato_il: str) -> None:
    _scrivi(
        dir_ / "connettore" / f"{codice}.json",
        {"codice_istat": codice, "controllato_il": controllato_il, "piattaforma": "hgate"},
    )


def _scena(tmp_path: Path) -> dict[str, Path]:
    catalog = tmp_path / "catalog"
    seed = tmp_path / "seed"
    live = tmp_path / "live"
    # Coverage: 2 hgate + 1 comweb + 1 WordPress alias eligible; magnolia excluded.
    _catalog_file(catalog, "001001", "hgate")
    _catalog_file(catalog, "001002", "hgate")
    _catalog_file(catalog, "001003", "comweb")
    _catalog_file(catalog, "001004", "wordpress_agid")
    _catalog_file(catalog, "001005", "magnolia")
    # A measurement store subdir must be ignored by the top-level glob.
    _scrivi(catalog / "municipality" / "ignored.json", {"not": "a comune"})

    # Demo: 2 MVP comuni (3 + 1 records) + curated (2 records).
    _scrivi(
        seed / "alfa_001001.json",
        [
            {"id": "a1", "source": {"fetched_at": "2026-08-01T10:00:00Z"}},
            {"id": "a2", "source": {"fetched_at": "2026-08-02T10:00:00Z"}},
            {"id": "a3", "source": {"fetched_at": "2026-07-30T10:00:00Z"}},
        ],
    )
    _scrivi(seed / "beta_001003.json", [{"id": "b1", "source": {"fetched_at": "2026-08-01T09:00:00Z"}}])
    _scrivi(seed / CURATED, [{"id": "c1"}, {"id": "c2"}])

    # Universe file.
    _scrivi(tmp_path / "comuni-istat.json", [{"codice_istat": f"{i:06d}"} for i in range(50)])
    return {"catalog": catalog, "seed": seed, "live": live, "istat": tmp_path / "comuni-istat.json"}


def _build(paths: dict[str, Path]):
    return build_monitoraggio(
        catalog_dir=paths["catalog"],
        seed_dir=paths["seed"],
        live_dir=paths["live"],
        comuni_istat_path=paths["istat"],
        curated_name=CURATED,
    )


def test_copertura_conteggi_e_eleggibilita(tmp_path: Path) -> None:
    r = _build(_scena(tmp_path))
    assert r.copertura.universo == 50
    assert r.copertura.catalogati == 5
    assert r.copertura.eleggibili == 4
    assert r.copertura.non_eleggibili == 1
    # Coverage arithmetic must always close.
    assert r.copertura.non_eleggibili == r.copertura.catalogati - r.copertura.eleggibili
    per = {p.piattaforma: p for p in r.copertura.per_piattaforma}
    assert per["hgate"].comuni == 2 and per["hgate"].eleggibile
    assert per["comweb"].eleggibile
    assert per["wordpress_agid"].eleggibile
    assert not per["magnolia"].eleggibile
    # Per-platform counts sum to catalogati.
    assert sum(p.comuni for p in r.copertura.per_piattaforma) == r.copertura.catalogati


def test_demo_conteggi_e_ultima_ingestion(tmp_path: Path) -> None:
    r = _build(_scena(tmp_path))
    assert r.demo.comuni == 2  # curated is NOT counted as a comune
    assert r.demo.record_totali == 4
    assert r.demo.curato_nazionale == 2
    assert r.demo.aggiornato_il is not None
    assert r.demo.aggiornato_il.startswith("2026-08-02")  # latest fetched_at


def test_refresh_inizializzati_e_mai_inizializzati(tmp_path: Path) -> None:
    paths = _scena(tmp_path)
    now = datetime.now(timezone.utc)
    _connettore(paths["live"], "001001", (now - timedelta(hours=1)).isoformat())
    _connettore(paths["live"], "001003", now.isoformat())
    r = _build(paths)
    assert r.refresh.inizializzati == 2
    assert r.refresh.eleggibili == 4
    assert r.refresh.mai_inizializzati == 2  # 4 eligible - 2 initialised
    assert r.refresh.fuori_perimetro == 0  # both initialised comuni are eligible
    assert r.refresh.ultimo_refresh is not None
    assert r.refresh.ultimo_refresh.startswith(now.strftime("%Y-%m-%d"))


def test_ultimo_refresh_usa_la_lettura_recente(tmp_path: Path) -> None:
    paths = _scena(tmp_path)
    _scrivi(paths["live"] / "connettore" / "001001.json", {
        "controllato_il": "2026-09-21T16:00:00+00:00",
        "letto_il": "2026-09-29T16:49:25+00:00",
    })
    assert _build(paths).refresh.ultimo_refresh == "2026-09-29T16:49:25+00:00"


def test_refresh_conta_solo_intersezione_eleggibile(tmp_path: Path) -> None:
    """`inizializzati` = eligible AND initialised, never a raw file count.

    A WordPress catalog record is eligible through its census alias. A record
    with no catalog entry remains outside the perimeter.
    """
    paths = _scena(tmp_path)
    now = datetime.now(timezone.utc)
    _connettore(paths["live"], "001001", now.isoformat())  # hgate, eligible
    _connettore(paths["live"], "001004", now.isoformat())  # WordPress alias, eligible
    _connettore(paths["live"], "999999", now.isoformat())  # not catalogued at all
    r = _build(paths)
    assert r.refresh.inizializzati == 2
    assert r.refresh.fuori_perimetro == 1     # only 999999 is outside
    assert r.refresh.mai_inizializzati == 2


def test_quadratura_perimetro(tmp_path: Path) -> None:
    """Coverage must close: catalogati = mai_inizializzati + inizializzati + non_eleggibili.

    The tiny fixture closes at 5 = 3 missing + 1 initialised + 1 ineligible.
    """
    paths = _scena(tmp_path)
    _connettore(paths["live"], "001001", datetime.now(timezone.utc).isoformat())
    r = _build(paths)
    assert (
        r.copertura.catalogati
        == r.refresh.mai_inizializzati + r.refresh.inizializzati + r.copertura.non_eleggibili
    )
    assert r.copertura.catalogati == 5
    assert r.refresh.mai_inizializzati == 3
    assert r.refresh.inizializzati == 1
    assert r.copertura.non_eleggibili == 1


def test_worker_sconosciuto_senza_sidecar(tmp_path: Path) -> None:
    r = _build(_scena(tmp_path))
    assert r.refresh.worker_stato == "sconosciuto"
    assert r.refresh.ultimo_batch is None
    # Refresh worker state must be its own component, "unknown" — not "down".
    sistemi = {c.nome: c for c in r.sistemi}
    assert sistemi["Refresh continuo"].stato == "unknown"


def test_worker_fermo_se_sidecar_vecchio(tmp_path: Path) -> None:
    paths = _scena(tmp_path)
    vecchio = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _scrivi(
        paths["live"] / "_worker_status.json",
        {"aggiornato_il": vecchio, "modo": "refresh", "ultimo_batch": {"comuni": 10, "eventi_429": 4}},
    )
    r = _build(paths)
    assert r.refresh.worker_stato == "fermo"
    assert r.refresh.ultimo_batch is not None
    assert r.refresh.ultimo_batch.eventi_429 == 4


def test_worker_attivo_se_sidecar_recente(tmp_path: Path) -> None:
    paths = _scena(tmp_path)
    recente = datetime.now(timezone.utc).isoformat()
    _scrivi(
        paths["live"] / "_worker_status.json",
        {
            "aggiornato_il": recente,
            "modo": "refresh",
            "ultimo_batch": {
                "comuni": 10, "tentati": 10, "riusciti": 9, "falliti": 1,
                "senza_contratto": 0, "eventi_429": 0, "domini_bloccati": 0,
                "durata_s": 42.0, "codice": 1,
            },
        },
    )
    r = _build(paths)
    assert r.refresh.worker_stato == "attivo"
    assert r.refresh.ultimo_batch.riusciti == 9
    assert r.refresh.ultimo_batch.durata_s == 42.0


def test_seed_non_guida_lo_stato_worker(tmp_path: Path) -> None:
    """A rich, recent demo layer must NOT make the refresh worker look healthy.

    This is the false-negative the old /api/status view produced in reverse:
    the two signals are independent and must stay independent.
    """
    paths = _scena(tmp_path)  # seed present and populated, no sidecar
    r = _build(paths)
    assert r.demo.comuni == 2 and r.demo.record_totali == 4
    assert r.refresh.worker_stato == "sconosciuto"  # despite a healthy demo


def test_sidecar_malformato_non_rompe(tmp_path: Path) -> None:
    paths = _scena(tmp_path)
    (paths["live"]).mkdir(parents=True, exist_ok=True)
    (paths["live"] / "_worker_status.json").write_text("{ not json", "utf-8")
    r = _build(paths)  # must not raise
    assert r.refresh.worker_stato == "sconosciuto"


def test_live_dir_assente_non_rompe(tmp_path: Path) -> None:
    paths = _scena(tmp_path)  # live dir never created
    r = _build(paths)
    assert r.refresh.inizializzati == 0
    assert r.refresh.fuori_perimetro == 0
    assert r.refresh.mai_inizializzati == r.refresh.eleggibili


# --- adherence synthesis: recognition fused with census coverage -------


def _riconoscimento_json(source_id: str, piattaforma: str) -> str:
    import json as _json

    return _json.dumps({
        "source_id": source_id, "surface": "ordinary_data", "platform_id": piattaforma,
        "connector_id": f"{piattaforma}_base", "connector_version": "1.0.0",
        "fingerprint_version": "1.0", "recognition_score": 0.99,
        "checked_at": "2026-10-03T10:00:00Z",
    })


def test_aderenza_fonde_riconoscimento_e_censimento(tmp_path) -> None:
    from treasureiq import monitoraggio as mod
    from treasureiq.storico import apri

    live = tmp_path / "live"
    cartella = live / "riconoscimento" / "ordinary_data"
    cartella.mkdir(parents=True)
    for codice, piattaforma in [
        ("001081", "comweb"),              # whole-model coverage -> verdict
        ("001082", "wordpress_generico"),  # exposed-schema coverage -> no verdict
        ("001083", "comweb"),              # census measured another family -> no coverage
        ("001084", "comweb"),              # never measured
    ]:
        (cartella / f"{codice}.json").write_text(_riconoscimento_json(codice, piattaforma), "utf-8")

    db = tmp_path / "storico.db"
    with apri(db, scrittura=True) as conn:
        for codice, piattaforma, aderenza, base in [
            ("001081", "comweb", 0.818, "modello_intero"),
            ("001082", "wp_design_comuni", 1.0, "schema_esposto"),
            ("001083", "peopleweb", 0.9, "modello_intero"),
        ]:
            conn.execute(
                "INSERT INTO portale_snapshot (rilevato_il, codice_istat, nome, indirizzabilita, "
                "recuperabilita, piattaforma, aderenza, base_misura) VALUES (?,?,?,?,?,?,?,?)",
                ("2026-08-20T00:00:00", codice, codice, "api_uffici", "ok", piattaforma, aderenza, base),
            )
        conn.commit()

    out = mod._aderenza(live, db)

    assert (out.riconosciuti, out.con_copertura, out.con_verdetto) == (4, 2, 1)
    comweb = next(r for r in out.per_piattaforma if r.piattaforma == "comweb")
    assert (comweb.riconosciuti, comweb.con_copertura, comweb.su_modello_intero) == (3, 1, 1)
    assert comweb.con_verdetto == 1 and comweb.verdetto_medio == 0.818
    wp = next(r for r in out.per_piattaforma if r.piattaforma == "wordpress_generico")
    assert (wp.con_copertura, wp.su_schema_esposto, wp.con_verdetto, wp.verdetto_medio) == (1, 1, 0, None)


def test_aderenza_senza_censimento_conta_solo_i_riconosciuti(tmp_path) -> None:
    from treasureiq import monitoraggio as mod

    cartella = tmp_path / "riconoscimento" / "ordinary_data"
    cartella.mkdir(parents=True)
    (cartella / "001081.json").write_text(_riconoscimento_json("001081", "comweb"), "utf-8")

    out = mod._aderenza(tmp_path, None)

    assert (out.riconosciuti, out.con_copertura, out.con_verdetto) == (1, 0, 0)



def test_aderenza_verdetto_solo_su_modello_intero_e_riconosciuti_veri(tmp_path) -> None:
    """QA repro: four ComWeb records with coverage 0.8 on bases NULL,
    'ignota', modello_intero, schema_esposto gave 3 verdicts for 1 whole-model
    measurement; an unrecognised record counted as recognised."""
    import json as _json

    from treasureiq import monitoraggio as mod
    from treasureiq.storico import apri

    cartella = tmp_path / "riconoscimento" / "ordinary_data"
    cartella.mkdir(parents=True)
    basi = {"001001": None, "001002": "ignota", "001003": "modello_intero", "001004": "schema_esposto"}
    for codice in basi:
        (cartella / f"{codice}.json").write_text(_riconoscimento_json(codice, "comweb"), "utf-8")
    ignoto = _json.loads(_riconoscimento_json("001005", "comweb"))
    ignoto.update(platform_id=None, recognition_score=0.0)
    (cartella / "001005.json").write_text(_json.dumps(ignoto), "utf-8")

    db = tmp_path / "storico.db"
    with apri(db, scrittura=True) as conn:
        for codice, base in basi.items():
            conn.execute(
                "INSERT INTO portale_snapshot (rilevato_il, codice_istat, nome, indirizzabilita, "
                "recuperabilita, piattaforma, aderenza, base_misura) VALUES (?,?,?,?,?,?,?,?)",
                ("2026-08-20T00:00:00", codice, codice, "solo_html", "ok", "comweb", 0.8, base),
            )
        conn.commit()

    out = mod._aderenza(tmp_path, db)

    assert (out.riconosciuti, out.non_riconosciuti) == (4, 1)
    assert [r.piattaforma for r in out.per_piattaforma] == ["comweb"]
    comweb = out.per_piattaforma[0]
    assert (comweb.con_copertura, comweb.su_modello_intero, comweb.su_schema_esposto) == (2, 1, 1)
    assert (comweb.con_verdetto, comweb.verdetto_medio) == (1, 0.8)
    assert out.con_verdetto == 1
