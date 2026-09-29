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
