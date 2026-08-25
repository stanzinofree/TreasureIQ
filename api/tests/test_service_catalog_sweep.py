"""Step 1 dello sweep di catalogo servizi: dry-run, zero rete, zero scritture.

Copre il pianificatore puro (`service_sweep.pianifica_dry_run`), il namespace
delle richieste (`service-catalog`, mai `chat`), la selezione a censimento di
`next_batch` e le due uscite di `run_batch` in modalità `service_catalog`
(dry-run → 0, esecuzione reale non pronta → uscita dedicata).
"""

from __future__ import annotations

from treasureiq import sweep_worker
from treasureiq.catalog import service_sweep
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_contracts import ServiceKey

TUTTE_LE_CHIAVI = tuple(ServiceKey)


# --------------------------------------------------------------------------- #
# Pianificatore puro
# --------------------------------------------------------------------------- #


def test_pianifica_classifica_i_tre_esiti():
    comuni = ["001", "002", "003"]

    def platform_di(source_id):
        return {"001": "wordpress_agid", "002": "ignota", "003": None}.get(source_id)

    def supportata(platform_id):
        return platform_id == "wordpress_agid"

    def in_cache(source_id, chiave):
        return False

    report = service_sweep.pianifica_dry_run(
        comuni, platform_di=platform_di, supportata=supportata, in_cache=in_cache
    )

    per_id = {r.source_id: r for r in report.righe}
    assert per_id["001"].esito == service_sweep.ESITO_PIANIFICATO
    assert per_id["002"].esito == service_sweep.ESITO_NON_SUPPORTATA
    assert per_id["003"].esito == service_sweep.ESITO_NO_MAPPA

    assert report.comuni_totali == 3
    assert report.comuni_pianificati == 1
    assert report.comuni_non_supportati == 1
    assert report.comuni_senza_mappa == 1


def test_pianifica_ripartisce_cache_e_da_risolvere():
    # Una chiave già in cache, le altre da risolvere.
    fresca = ServiceKey.CARTA_IDENTITA

    def platform_di(source_id):
        return "comweb"

    def supportata(platform_id):
        return True

    def in_cache(source_id, chiave):
        return chiave is fresca

    report = service_sweep.pianifica_dry_run(
        ["058091"], platform_di=platform_di, supportata=supportata, in_cache=in_cache
    )

    riga = report.righe[0]
    assert riga.chiavi_in_cache == (fresca,)
    assert set(riga.chiavi_da_risolvere) == set(TUTTE_LE_CHIAVI) - {fresca}
    assert report.chiavi_in_cache == 1
    assert report.chiavi_da_risolvere == len(TUTTE_LE_CHIAVI) - 1


def test_aggregato_per_piattaforma_e_risoluzioni_stimate():
    def platform_di(source_id):
        return "comweb" if source_id.startswith("A") else "wordpress_agid"

    def supportata(platform_id):
        return True

    def in_cache(source_id, chiave):
        return False

    report = service_sweep.pianifica_dry_run(
        ["A1", "A2", "B1"],
        platform_di=platform_di,
        supportata=supportata,
        in_cache=in_cache,
    )

    per_pf = {a.platform_id: a for a in report.per_piattaforma}
    assert per_pf["comweb"].comuni == 2
    assert per_pf["wordpress_agid"].comuni == 1
    # Nessuna cache: ogni chiave è una risoluzione da tentare.
    assert per_pf["comweb"].risoluzioni_da_tentare == 2 * len(TUTTE_LE_CHIAVI)
    assert per_pf["wordpress_agid"].risoluzioni_da_tentare == len(TUTTE_LE_CHIAVI)
    assert report.risoluzioni_da_tentare == 3 * len(TUTTE_LE_CHIAVI)


def test_pianifica_su_lotto_vuoto():
    report = service_sweep.pianifica_dry_run(
        [], platform_di=lambda s: None, supportata=lambda p: True, in_cache=lambda s, k: False
    )
    assert report.comuni_totali == 0
    assert report.per_piattaforma == ()


# --------------------------------------------------------------------------- #
# Namespace richieste
# --------------------------------------------------------------------------- #


def test_service_request_namespace_service_catalog():
    richiesta = service_request(
        source_id="058091",
        service_key=ServiceKey.CARTA_IDENTITA,
        namespace="service-catalog",
    )
    assert richiesta.request_id.startswith("service-catalog:")
    assert "chat:" not in richiesta.request_id


def test_service_request_namespace_default_chat():
    richiesta = service_request(source_id="058091", service_key=ServiceKey.CARTA_IDENTITA)
    assert richiesta.request_id.startswith("chat:")


# --------------------------------------------------------------------------- #
# Wiring sweep_worker
# --------------------------------------------------------------------------- #


def test_next_batch_service_catalog_censisce_tutto(tmp_path, monkeypatch):
    config = sweep_worker.WorkerConfig(db=tmp_path / "storico.db", mode="service_catalog")
    monkeypatch.setattr(
        sweep_worker, "_comuni_da_censimento", lambda db: ["001", "002", "003", "004"]
    )
    # Nessun cap a batch_size: il censimento vede tutti i comuni.
    assert sweep_worker.next_batch(config) == ["001", "002", "003", "004"]


def test_run_batch_service_catalog_reale_non_pronto(tmp_path):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="service_catalog", dry_run=False
    )
    assert (
        sweep_worker.run_batch(config, ["001"]) == sweep_worker.EXIT_SERVICE_REAL_NOT_READY
    )


def test_run_batch_service_catalog_dry_run_non_scrive(tmp_path, monkeypatch):
    config = sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="service_catalog", dry_run=True
    )

    # Seam fittizi: nessuna rete, nessun registry reale.
    def fake_seam(_config):
        platform_di = lambda s: "wordpress_agid"  # noqa: E731
        supportata = lambda p: True  # noqa: E731
        in_cache = lambda s, k: False  # noqa: E731
        return platform_di, supportata, in_cache

    monkeypatch.setattr(sweep_worker, "_seam_servizi", fake_seam)

    assert sweep_worker.run_batch(config, ["001", "002"]) == 0
