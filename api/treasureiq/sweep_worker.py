"""Worker continuo per lo sweep dei comuni già censiti come leggibili.

Il worker orchestra il comando ``registro_cli sweep``: non duplica né il
motore di censimento né i connettori. Il database resta la fonte di verità per
il resume giornaliero, quindi un riavvio non ripete i comuni già misurati.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from treasureiq.ingest.censimento import _gia_registrati
from treasureiq.catalog.confirmation import confirm_inventory
from treasureiq.catalog.fetch_policy import PoliticaFetch
from treasureiq.catalog.fetch_runtime import EsecutoreFetch
from treasureiq.catalog.inventory_discovery import discover_source_inventory
from treasureiq.connettore import _da_store_raw as _connettore_cache
from treasureiq.registro_cli import _comuni_da_censimento, main as sweep_main
from treasureiq.storico import apri
from treasureiq.sonda_live import LIVE_DIR, comune_per_codice

logger = logging.getLogger("treasureiq.sweep_worker")

# Exit code emesso da run_batch quando un batch non è stato eseguito ma
# deliberatamente rifiutato (oggi: refresh sotto --dry-run). Distinto da 0
# (eseguito ok) e da 1 (eseguito con errori) così il chiamante non confonde
# "rifiutato" con "riuscito".
EXIT_REFRESH_SKIPPED = 2


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
    # Cortesia verso i portali (usata dalla confirmation via PoliticaFetch):
    # intervallo minimo fra due fetch sullo stesso dominio e tetto di fetch per
    # dominio per lotto. Il backoff sui fallimenti di rete parte da questa base.
    intervallo_dominio_s: float = 1.0
    budget_per_dominio: int = 50
    backoff_base_s: float = 60.0
    backoff_cap_s: float = 3600.0


def config_from_env(
    *, db: Path | None = None, once: bool = False, dry_run: bool = False,
) -> WorkerConfig:
    """Legge la configurazione solo da env, con default conservativi."""

    resolved_db = db or Path(os.environ.get("TREASUREIQ_SWEEP_DB", "/scrivibile/storico.db"))
    mode = os.environ.get("TREASUREIQ_SWEEP_MODE", "refresh").strip().lower()
    if mode not in {"refresh", "confirmation", "discovery"}:
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
    )


def next_batch(config: WorkerConfig) -> list[str]:
    """Seleziona un lotto secondo la modalità, senza discovery ripetuta."""

    comuni = _comuni_da_censimento(config.db)
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


def run_batch(config: WorkerConfig, comuni: list[str]) -> int:
    """Esegue un lotto riusando il CLI esistente.

    Il refresh non passa dal censimento: usa il registro/connettore con cache
    e quindi non ripete la discovery della piattaforma. La discovery esplicita
    mantiene invece il percorso nazionale completo e aggiorna il catalogo.
    """

    if not comuni:
        return 0
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
        "--mode", choices=("refresh", "confirmation", "discovery"), default=None
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Esegue lo sweep senza scrivere data-live (refresh rifiutato).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = config_from_env(db=args.db, once=args.once, dry_run=args.dry_run)
    if config.dry_run:
        logger.info("dry-run attivo: nessuna scrittura su data-live")
    if args.mode:
        config = replace(config, mode=args.mode)
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
