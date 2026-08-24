"""Worker continuo per lo sweep dei comuni già censiti come leggibili.

Il worker orchestra il comando ``registro_cli sweep``: non duplica né il
motore di censimento né i connettori. Il database resta la fonte di verità per
il resume giornaliero, quindi un riavvio non ripete i comuni già misurati.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from treasureiq.catalog import service_cache
from treasureiq.catalog.confirmation import confirm_inventory
from treasureiq.catalog.data_contracts import FreshnessPolicy
from treasureiq.catalog.fetch_policy import PoliticaFetch
from treasureiq.catalog.fetch_runtime import EsecutoreFetch
from treasureiq.catalog.inventory_discovery import discover_source_inventory
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.catalog.service_registry import default_service_registry
from treasureiq.catalog.service_resolver import resolve_service_with_meta
from treasureiq.catalog.service_sweep import (
    ServiceSweepDryReport,
    pianifica_dry_run,
)
from treasureiq.connettore import _da_store_raw as _connettore_cache
from treasureiq.ingest.censimento import _gia_registrati
from treasureiq.mappa_connettore import (
    ProbeBudgetEsaurito,
    ProbeFallita,
    mappa_connettore,
)
from treasureiq.mappa_connettore import _da_cache as _mappa_da_cache
from treasureiq.registro import leggi_registro
from treasureiq.registro_cli import _comuni_da_censimento
from treasureiq.registro_cli import main as sweep_main
from treasureiq.sonda_live import LIVE_DIR, comune_per_codice
from treasureiq.storico import apri

logger = logging.getLogger("treasureiq.sweep_worker")

# Exit code emesso da run_batch quando un batch non è stato eseguito ma
# deliberatamente rifiutato (oggi: refresh sotto --dry-run). Distinto da 0
# (eseguito ok) e da 1 (eseguito con errori) così il chiamante non confonde
# "rifiutato" con "riuscito".
EXIT_REFRESH_SKIPPED = 2
#: `service_catalog` senza `--dry-run` né `--execute`: l'esecuzione reale è
#: dietro un gate esplicito.  Uscita dedicata così l'invocazione non fa nulla in
#: silenzio.  Emessa anche quando un lotto reale non è ⊆ campione pinnato.
EXIT_SERVICE_REAL_NOT_READY = 3
#: Run reale `service_catalog`: il lotto è stato completato ma uno o più comuni
#: hanno sollevato un errore.  Distinto da 0 così l'operatore sa che il campione
#: ha buchi da guardare prima di fidarsi dei numeri.
EXIT_SERVICE_PARTIAL_ERRORS = 4
#: Run reale `service_catalog`: il budget-per-dominio si è esaurito durante una
#: probe mappa guardata.  Il run si ferma onesto — nessuna risoluzione servizi
#: speculativa oltre il muro, nessuna mappa fabbricata.
EXIT_SERVICE_BUDGET_BLOCKED = 5

#: Campione pinnato per il primo run reale (con rete) dello sweep servizi —
#: docs/workstreams/rami-connettore/service-catalog-campione-20.md.  Il run
#: reale rifiuta qualunque lotto non ⊆ questo insieme: il fan-out nazionale
#: resta dietro un gate esplicito, non un flag.
CAMPIONE_SERVICE_CATALOG_20: tuple[str, ...] = (
    "001001", "002007", "003001", "004005", "006002", "007002",
    "001028", "003008", "003084", "003095", "004009", "006009",
    "020060", "023002", "024002", "025004",
    "004059", "004203",
    "007060", "012085",
)

#: I quattro esiti possibili per una risoluzione `ServiceKey` nel run reale.
#: `da_cache`/`risolto_live` = trovato; `miss` = risolto ma nessuna reference;
#: `senza_mappa` = nessuna mappa-connettore, la risoluzione non è nemmeno tentata.
_ESITI_CHIAVE: tuple[str, ...] = ("da_cache", "risolto_live", "miss", "senza_mappa")


def _nuovo_esecutore(config: "WorkerConfig") -> EsecutoreFetch:
    """Un esecutore per lotto: budget e rate-limit sono per dominio, quindi
    devono ricordare gli host già toccati dagli altri comuni dello stesso lotto
    (tipico: un host SaaS di trasparenza condiviso da molti comuni). Lo stesso
    argine vale per discovery e confirmation."""
    return EsecutoreFetch(
        PoliticaFetch(
            intervallo_minimo_s=config.intervallo_dominio_s,
            massimo_per_dominio=config.budget_per_dominio,
            backoff_base_s=config.backoff_base_s,
            backoff_cap_s=config.backoff_cap_s,
        )
    )


@dataclass(frozen=True)
class WorkerConfig:
    db: Path
    batch_size: int = 20
    interval_seconds: float = 120.0
    lavoratori: int = 6
    delay: float = 0.0
    aderenza: bool = False
    mode: str = "confirmation"
    discovery_interval_days: int = 14
    confirmation_interval_seconds: float = 15 * 86400.0
    refresh_interval_seconds: float = 86400.0
    once: bool = False
    dry_run: bool = False
    #: Gate del run reale `service_catalog`: senza questo (e senza `dry_run`) il
    #: comando non fa nulla e ritorna `EXIT_SERVICE_REAL_NOT_READY`.  Il run reale
    #: gira SOLO sul campione pinnato; il fan-out nazionale resta fuori.
    execute: bool = False
    # Cortesia verso i portali (usata dalla confirmation via PoliticaFetch):
    # intervallo minimo fra due fetch sullo stesso dominio e tetto di fetch per
    # dominio per lotto. Il backoff sui fallimenti di rete parte da questa base.
    intervallo_dominio_s: float = 1.0
    budget_per_dominio: int = 50
    backoff_base_s: float = 60.0
    backoff_cap_s: float = 3600.0
    #: Freschezza cache servizi usata dal dry-run del catalogo: una voce più
    #: giovane di questa soglia conta come "già in cache" (nessuna risoluzione).
    service_max_age_seconds: float = 86400.0


def config_from_env(
    *, db: Path | None = None, once: bool = False, dry_run: bool = False,
    execute: bool = False,
) -> WorkerConfig:
    """Legge la configurazione solo da env, con default conservativi."""

    resolved_db = db or Path(os.environ.get("TREASUREIQ_SWEEP_DB", "/scrivibile/storico.db"))
    mode = os.environ.get("TREASUREIQ_SWEEP_MODE", "refresh").strip().lower()
    if mode not in {"refresh", "confirmation", "discovery", "service_catalog"}:
        logger.warning("modalità sweep sconosciuta %r: uso refresh", mode)
        mode = "refresh"
    return WorkerConfig(
        db=resolved_db,
        batch_size=max(1, int(os.environ.get("TREASUREIQ_SWEEP_BATCH_SIZE", "20"))),
        interval_seconds=max(
            0.0, float(os.environ.get("TREASUREIQ_SWEEP_INTERVAL_SECONDS", "120"))
        ),
        lavoratori=max(1, int(os.environ.get("TREASUREIQ_SWEEP_WORKERS", "6"))),
        delay=max(0.0, float(os.environ.get("TREASUREIQ_SWEEP_DELAY", "0"))),
        aderenza=os.environ.get("TREASUREIQ_SWEEP_ADERENZA", "0") == "1",
        mode=mode,
        discovery_interval_days=max(
            1, int(os.environ.get("TREASUREIQ_DISCOVERY_INTERVAL_DAYS", "14"))
        ),
        confirmation_interval_seconds=max(
            60.0,
            float(
                os.environ.get(
                    "TREASUREIQ_CONFIRMATION_INTERVAL_SECONDS", str(15 * 86400)
                )
            ),
        ),
        refresh_interval_seconds=max(
            60.0, float(os.environ.get("TREASUREIQ_REFRESH_INTERVAL_SECONDS", "86400"))
        ),
        intervallo_dominio_s=max(
            0.0, float(os.environ.get("TREASUREIQ_FETCH_INTERVALLO_DOMINIO_S", "1"))
        ),
        budget_per_dominio=max(
            1, int(os.environ.get("TREASUREIQ_FETCH_BUDGET_DOMINIO", "50"))
        ),
        backoff_base_s=max(
            0.0, float(os.environ.get("TREASUREIQ_FETCH_BACKOFF_BASE_S", "60"))
        ),
        backoff_cap_s=max(
            0.0, float(os.environ.get("TREASUREIQ_FETCH_BACKOFF_CAP_S", "3600"))
        ),
        once=once,
        dry_run=dry_run or os.environ.get("TREASUREIQ_SWEEP_DRY_RUN", "0") == "1",
        execute=execute or os.environ.get("TREASUREIQ_SERVICE_EXECUTE", "0") == "1",
        service_max_age_seconds=max(
            0.0, float(os.environ.get("TREASUREIQ_SERVICE_MAX_AGE_SECONDS", "86400"))
        ),
    )


def next_batch(config: WorkerConfig) -> list[str]:
    """Seleziona un lotto secondo la modalità, senza discovery ripetuta."""

    comuni = _comuni_da_censimento(config.db)
    if config.mode == "service_catalog":
        if config.execute and not config.dry_run:
            # Run reale: SOLO il campione pinnato, intersecato col censimento
            # (si eseguono solo comuni noti). Il fan-out nazionale resta fuori.
            noti = set(comuni)
            lotto = [c for c in CAMPIONE_SERVICE_CATALOG_20 if c in noti]
            mancanti = [c for c in CAMPIONE_SERVICE_CATALOG_20 if c not in noti]
            if mancanti:
                logger.warning(
                    "service_catalog reale: %d comuni del campione non sono nel "
                    "censimento e verranno saltati: %s",
                    len(mancanti), ", ".join(mancanti),
                )
            return lotto
        # Il dry-run del catalogo servizi è un censimento: classifica TUTTI i
        # comuni (supportati, non supportati, senza mappa), non un lotto da 20.
        return list(comuni)
    if config.mode in {"refresh", "confirmation"}:
        intervallo = (
            config.confirmation_interval_seconds
            if config.mode == "confirmation"
            else config.refresh_interval_seconds
        )
        limite = datetime.now(timezone.utc) - timedelta(seconds=intervallo)
        candidati: list[str] = []
        for codice in comuni:
            # Un refresh non deve diventare discovery per un comune senza
            # contratto connettore: quello è lavoro della modalità discovery.
            record = _connettore_cache(codice)
            if record is None:
                continue
            try:
                letto = datetime.fromisoformat(record.controllato_il or record.letto_il)
            except ValueError:
                candidati.append(codice)
                continue
            if letto.tzinfo is None:
                letto = letto.replace(tzinfo=timezone.utc)
            if letto <= limite:
                candidati.append(codice)
        candidati.sort(
            key=lambda codice: (
                (_connettore_cache(codice).letto_il if _connettore_cache(codice) else ""),
                codice,
            )
        )
        return candidati[: config.batch_size]

    oggi = datetime.now(timezone.utc).date()
    gia_fatti = _gia_registrati(config.db, oggi)
    scadenza = oggi - timedelta(days=config.discovery_interval_days)
    ultime = {}
    if config.db.exists():
        with apri(config.db) as conn:
            ultime = {
                row["codice_istat"]: row["rilevato_il"]
                for row in conn.execute(
                    "SELECT codice_istat, MAX(rilevato_il) AS rilevato_il "
                    "FROM portale_snapshot GROUP BY codice_istat"
                ).fetchall()
            }
    candidati = [
        codice
        for codice in comuni
        if codice not in gia_fatti
        and (
            codice not in ultime
            or not ultime[codice]
            or datetime.fromisoformat(ultime[codice]).date() <= scadenza
        )
    ]
    return candidati[: config.batch_size]


def _seam_servizi(config: WorkerConfig):
    """Costruisce i tre seam del dry-run servizi senza toccare la rete.

    L'``EsecutoreFetch`` e il registry vengono istanziati (nessun fetch al
    costruttore), ma il dry-run non chiama mai ``retrieve``: usa il registry
    solo come predicato di supporto (``resolve`` esamina surface/capability/
    platform_id) e legge la cache servizi da disco.  Namespace richieste
    ``service-catalog``, mai ``chat`` — così budget e telemetria dello sweep
    restano separati dalla chat live.
    """
    esecutore = _nuovo_esecutore(config)
    registry = default_service_registry(esecutore)
    policy = FreshnessPolicy(max_age_seconds=config.service_max_age_seconds)
    prima_chiave = next(iter(ServiceKey))
    supporto_per_pf: dict[str, bool] = {}

    def platform_di(source_id: str) -> str | None:
        # La piattaforma catalogata vive nel registro (CONTRATTO-O2), non nella
        # mappa-connettore: `leggi_registro` è cache-only (solo disco, nessuna
        # rete) e ritorna None per i comuni mai scansionati.
        record = leggi_registro(source_id)
        return record.piattaforma if record else None

    def supportata(platform_id: str) -> bool:
        if platform_id not in supporto_per_pf:
            richiesta = service_request(
                source_id="000000",
                service_key=prima_chiave,
                namespace="service-catalog",
            )
            connettore = registry.resolve(request=richiesta, platform_id=platform_id)
            supporto_per_pf[platform_id] = connettore is not None
        return supporto_per_pf[platform_id]

    def in_cache(source_id: str, chiave: ServiceKey) -> bool:
        return service_cache.carica(source_id, chiave, policy=policy) is not None

    return platform_di, supportata, in_cache


def _loga_report_servizi(report: ServiceSweepDryReport) -> None:
    logger.info(
        "service_catalog dry-run: %d comuni — pianificati %d, non supportati %d, "
        "senza piattaforma nota %d",
        report.comuni_totali,
        report.comuni_pianificati,
        report.comuni_non_supportati,
        report.comuni_senza_mappa,
    )
    logger.info(
        "service_catalog dry-run: chiavi in cache %d, da risolvere %d "
        "(risoluzioni da tentare, non richieste HTTP)",
        report.chiavi_in_cache,
        report.chiavi_da_risolvere,
    )
    for agg in report.per_piattaforma:
        logger.info(
            "  %-24s comuni=%-5d cache=%-5d da_risolvere=%d",
            agg.platform_id,
            agg.comuni,
            agg.chiavi_in_cache,
            agg.chiavi_da_risolvere,
        )


def _run_service_catalog(config: WorkerConfig, comuni: list[str]) -> int:
    """Instrada il catalogo servizi: dry-run, gate reale, o run reale.

    - ``--dry-run`` → fotografia net-free (censimento, zero rete, zero scritture);
    - né dry-run né ``--execute`` → gate esplicito, nessuna azione (uscita 3);
    - ``--execute`` → run reale sul solo campione pinnato (rete via executor
      guardato, cache servizi scritta dal resolver, metriche atomiche).
    """
    if config.dry_run:
        platform_di, supportata, in_cache = _seam_servizi(config)
        report = pianifica_dry_run(
            comuni, platform_di=platform_di, supportata=supportata, in_cache=in_cache
        )
        _loga_report_servizi(report)
        return 0
    if not config.execute:
        logger.warning(
            "service_catalog: esecuzione reale dietro gate esplicito. Usa "
            "--execute per il run reale sul campione pinnato, o --dry-run per la "
            "fotografia net-free. Nessuna azione su %d comuni.",
            len(comuni),
        )
        return EXIT_SERVICE_REAL_NOT_READY
    return _esegui_service_catalog(config, comuni)


def _percorso_metriche_servizi() -> Path:
    return LIVE_DIR / "service-catalog-metriche" / "ultimo.json"


def _scrivi_metriche_servizi(metriche: dict) -> None:
    """Scrittura atomica delle metriche per-run (mai in storico.db).

    Riscritta per intero dopo ogni comune: un run interrotto lascia comunque
    l'ultimo stato coerente su disco, e la ripresa riparte dalla cache servizi
    (che è lo stato vero), non da questo file.
    """
    percorso = _percorso_metriche_servizi()
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(
            json.dumps(metriche, ensure_ascii=False, indent=2), "utf-8"
        )
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("metriche service_catalog non scrivibili (%s): %s", percorso, exc)


def _metriche_iniziali(totale: int) -> dict:
    """Lo scheletro delle metriche per-run, con i contatori a zero."""
    return {
        "avviato_il": datetime.now(timezone.utc).isoformat(),
        "modo": "service_catalog",
        "campione": "20-pinnato",
        "comuni_totali": totale,
        "comuni_completati": 0,
        "budget_esaurito": False,
        "esito_comuni": {"errore": 0},
        "esito_chiavi": {esito: 0 for esito in _ESITI_CHIAVE},
        # Il costo della probe mappa è contato a parte dalle risoluzioni: un
        # comune su cache-mappa non tocca la rete per la mappa, uno live sì.
        "probe": {
            "comuni_da_cache_mappa": 0,
            "comuni_probati_live": 0,
            "probe_fallite": 0,
        },
        "per_piattaforma": {},
        "per_comune": [],
    }


def _esito_chiave(
    chiave: ServiceKey,
    codice: str,
    mappa,
    platform_id: str,
    registry,
    freshness: FreshnessPolicy,
) -> str:
    """Risolve una `ServiceKey` e classifica l'esito, cache-first.

    Senza mappa la risoluzione non è nemmeno tentata (`senza_mappa`): il
    resolver richiede una `MappaConnettore`, e fabbricarne una vuota
    produrrebbe miss speculativi. Un budget esaurito a livello di risoluzione
    (connettore) degrada a `miss` onesto — solo la probe mappa ferma il run.
    """
    if mappa is None:
        return "senza_mappa"
    richiesta = service_request(
        source_id=codice,
        service_key=chiave,
        freshness=freshness,
        namespace="service-catalog",
    )
    resolved = resolve_service_with_meta(
        richiesta, mappa=mappa, registry=registry, platform_id=platform_id
    )
    if resolved is None:
        return "miss"
    return "da_cache" if resolved.from_cache else "risolto_live"


def _risolvi_comune_servizi(
    codice: str, *, registry, esecutore, freshness: FreshnessPolicy, metriche: dict
) -> dict:
    """Risolve le 5 `ServiceKey` di un comune; ritorna la sua riga di metriche.

    La mappa arriva dalla cache (nessuna rete) o da una probe live guardata; la
    probe live può sollevare `ProbeBudgetEsaurito` (propagata: ferma il run) o
    `ProbeFallita` (miss onesto: nessuna mappa, nessuna risoluzione tentata).
    """
    record = leggi_registro(codice)
    platform_id = record.piattaforma if record else ""
    riga: dict = {
        "source_id": codice,
        "piattaforma": platform_id or None,
        "mappa": None,
        "chiavi": {},
    }

    cache_mappa = _mappa_da_cache(codice)
    if cache_mappa is not None:
        mappa = cache_mappa
        riga["mappa"] = "cache"
        metriche["probe"]["comuni_da_cache_mappa"] += 1
    else:
        metriche["probe"]["comuni_probati_live"] += 1
        try:
            mappa = mappa_connettore(codice, esecutore=esecutore)
            riga["mappa"] = "live"
        except ProbeFallita:
            mappa = None
            riga["mappa"] = "probe_fallita"
            metriche["probe"]["probe_fallite"] += 1

    pf = metriche["per_piattaforma"].setdefault(
        platform_id or "ignota",
        {"comuni": 0, **{esito: 0 for esito in _ESITI_CHIAVE}},
    )
    pf["comuni"] += 1

    for chiave in ServiceKey:
        esito = _esito_chiave(chiave, codice, mappa, platform_id, registry, freshness)
        riga["chiavi"][chiave.value] = esito
        metriche["esito_chiavi"][esito] += 1
        pf[esito] += 1
    return riga


def _loga_metriche_servizi(metriche: dict) -> None:
    e = metriche["esito_chiavi"]
    p = metriche["probe"]
    logger.info(
        "service_catalog reale: %d/%d comuni — chiavi cache=%d live=%d miss=%d "
        "senza_mappa=%d; probe live=%d cache=%d fallite=%d; budget_esaurito=%s",
        metriche["comuni_completati"], metriche["comuni_totali"],
        e["da_cache"], e["risolto_live"], e["miss"], e["senza_mappa"],
        p["comuni_probati_live"], p["comuni_da_cache_mappa"], p["probe_fallite"],
        metriche["budget_esaurito"],
    )


def _esegui_service_catalog(config: WorkerConfig, comuni: list[str]) -> int:
    """Run reale del catalogo servizi sul campione pinnato.

    Rete solo attraverso l'executor guardato dello sweep (host guard, budget,
    rate-limit); la cache servizi è scritta dal resolver su FULFILLED; le
    metriche sono riscritte in modo atomico dopo ogni comune.  Il fan-out
    nazionale resta fuori: un lotto non ⊆ campione pinnato è rifiutato.
    """
    ammessi = set(CAMPIONE_SERVICE_CATALOG_20)
    fuori = [c for c in comuni if c not in ammessi]
    if fuori:
        logger.error(
            "service_catalog reale: lotto non ⊆ campione pinnato (%d comuni fuori, "
            "es. %s). Il fan-out nazionale resta dietro un gate esplicito.",
            len(fuori), ", ".join(fuori[:5]),
        )
        return EXIT_SERVICE_REAL_NOT_READY

    esecutore = _nuovo_esecutore(config)
    registry = default_service_registry(esecutore)
    freshness = FreshnessPolicy(max_age_seconds=config.service_max_age_seconds)
    metriche = _metriche_iniziali(len(comuni))
    errori = 0

    for codice in comuni:
        try:
            riga = _risolvi_comune_servizi(
                codice,
                registry=registry,
                esecutore=esecutore,
                freshness=freshness,
                metriche=metriche,
            )
        except ProbeBudgetEsaurito:
            # Budget del dominio esaurito durante la probe mappa: run fermato
            # onesto. Il comune corrente resta senza risoluzioni speculative.
            metriche["budget_esaurito"] = True
            metriche["per_comune"].append(
                {"source_id": codice, "esito_comune": "budget_bloccato", "chiavi": {}}
            )
            _scrivi_metriche_servizi(metriche)
            _loga_metriche_servizi(metriche)
            logger.warning(
                "service_catalog: budget dominio esaurito su %s, run fermato", codice
            )
            return EXIT_SERVICE_BUDGET_BLOCKED
        except Exception:  # noqa: BLE001 — un comune non ferma il lotto
            logger.exception("service_catalog: risoluzione fallita per %s", codice)
            errori += 1
            metriche["esito_comuni"]["errore"] += 1
            metriche["per_comune"].append(
                {"source_id": codice, "esito_comune": "errore", "chiavi": {}}
            )
        else:
            metriche["per_comune"].append(riga)
        metriche["comuni_completati"] += 1
        _scrivi_metriche_servizi(metriche)
        if config.delay:
            time.sleep(config.delay)

    _loga_metriche_servizi(metriche)
    return EXIT_SERVICE_PARTIAL_ERRORS if errori else 0


def run_batch(config: WorkerConfig, comuni: list[str]) -> int:
    """Esegue un lotto riusando il CLI esistente.

    Il refresh non passa dal censimento: usa il registro/connettore con cache
    e quindi non ripete la discovery della piattaforma. La discovery esplicita
    mantiene invece il percorso nazionale completo e aggiorna il catalogo.
    """

    if not comuni:
        return 0
    if config.mode == "service_catalog":
        return _run_service_catalog(config, comuni)
    if config.mode == "discovery":
        errors = 0
        # Stesso runtime di fetch della confirmation: anche la discovery
        # periodica passa da rate-limit e budget per dominio (anti-flooding).
        esecutore = _nuovo_esecutore(config)
        for codice in comuni:
            try:
                comune = comune_per_codice(codice)
                if comune is None or not comune.sito:
                    raise ValueError("base_url_missing")
                inventory = discover_source_inventory(
                    live_dir=LIVE_DIR, source_id=codice, base_url=comune.sito,
                    dry_run=config.dry_run, esecutore=esecutore,
                )
                logger.info(
                    "discovery %s: base=%s at=%s sp=%d",
                    codice,
                    inventory.base_platform if inventory else "unknown",
                    inventory.transparency_platform if inventory else "unknown",
                    len(inventory.service_portals) if inventory else 0,
                )
            except Exception:  # noqa: BLE001 — un comune non ferma il lotto
                logger.exception("discovery inventario fallita per %s", codice)
                errors += 1
            if config.delay:
                time.sleep(config.delay)
        return 1 if errors else 0
    if config.mode == "refresh":
        if config.dry_run:
            # Il refresh scrive lo storico via il CLI legacy (sweep_main), fuori
            # dalla guardia dry_run del path catalog: non lo simuliamo, lo
            # rifiutiamo, così --dry-run non muta mai dati (invariante I4).
            logger.warning(
                "dry-run: modalità refresh non supportata (scrive lo storico "
                "via path legacy); nessuna azione su %d comuni", len(comuni),
            )
            # Exit code dedicato: il chiamante distingue "rifiutato" (SKIPPED) da
            # "eseguito con successo" (0). run() lo propaga e ferma il ciclo.
            return EXIT_REFRESH_SKIPPED
        argv = [
            "scan", *comuni, "--db", str(config.db), "--refresh-dati",
            "--delay", str(config.delay),
        ]
    elif config.mode == "confirmation":
        errors = 0
        esecutore = _nuovo_esecutore(config)
        for codice in comuni:
            try:
                results = confirm_inventory(
                    live_dir=LIVE_DIR, source_id=codice, dry_run=config.dry_run,
                    esecutore=esecutore,
                )
                logger.info(
                    "confirmation %s: %s",
                    codice,
                    ", ".join(f"{r.surface.value}={r.status.value}" for r in results),
                )
            except Exception:  # noqa: BLE001 — un comune non ferma il lotto
                logger.exception("confirmation fallita per %s", codice)
                errors += 1
            if config.delay:
                time.sleep(config.delay)
        return 1 if errors else 0
    else:
        raise ValueError(f"modalità worker non gestita: {config.mode}")
    # A questo punto mode è garantito "refresh": discovery e confirmation sono
    # già ritornati sopra, ogni altro valore ha sollevato. L'aderenza è calcolata
    # dal path legacy (sweep_main), quindi il flag va propagato qui.
    if config.aderenza:
        argv.append("--aderenza")
    return sweep_main(argv)


def run(config: WorkerConfig) -> int:
    """Ciclo batch→pausa, senza sovrapporre due sweep."""

    while True:
        comuni = next_batch(config)
        if not comuni:
            logger.info("nessun comune residuo nel ciclo giornaliero")
            if config.once:
                return 0
            # Keep the long-running container alive until the next UTC day;
            # exiting would make restart: unless-stopped spin the container.
            time.sleep(max(config.interval_seconds, 60.0))
            continue
        started = time.monotonic()
        logger.info("avvio batch: %d comuni (%s)", len(comuni), ", ".join(comuni))
        result = run_batch(config, comuni)
        elapsed = time.monotonic() - started
        logger.info("batch terminato: %d comuni in %.1fs, codice=%d", len(comuni), elapsed, result)
        if result != 0:
            return result
        if config.once:
            return 0
        logger.info("pausa %.0fs prima del prossimo batch", config.interval_seconds)
        time.sleep(config.interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker Docker per sweep incrementale.")
    parser.add_argument("--once", action="store_true", help="Esegue un solo batch e termina.")
    parser.add_argument("--db", type=Path, default=None, help="Override del database storico.")
    parser.add_argument(
        "--mode",
        choices=("refresh", "confirmation", "discovery", "service_catalog"),
        default=None,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Esegue lo sweep senza scrivere data-live (refresh rifiutato).",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help=(
            "Gate del run reale service_catalog: senza questo il comando non fa "
            "nulla. Gira SOLO sul campione pinnato da 20 (nessun fan-out nazionale)."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = config_from_env(
        db=args.db, once=args.once, dry_run=args.dry_run, execute=args.execute
    )
    if config.dry_run:
        logger.info("dry-run attivo: nessuna scrittura su data-live")
    if args.mode:
        config = replace(config, mode=args.mode)
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
