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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from treasureiq.ingest.censimento import _gia_registrati
from treasureiq.registro_cli import _comuni_da_censimento, main as sweep_main

logger = logging.getLogger("treasureiq.sweep_worker")


@dataclass(frozen=True)
class WorkerConfig:
    db: Path
    batch_size: int = 20
    interval_seconds: float = 120.0
    lavoratori: int = 6
    delay: float = 0.0
    aderenza: bool = False
    once: bool = False


def config_from_env(*, db: Path | None = None, once: bool = False) -> WorkerConfig:
    """Legge la configurazione solo da env, con default conservativi."""

    resolved_db = db or Path(os.environ.get("TREASUREIQ_SWEEP_DB", "/scrivibile/storico.db"))
    return WorkerConfig(
        db=resolved_db,
        batch_size=max(1, int(os.environ.get("TREASUREIQ_SWEEP_BATCH_SIZE", "20"))),
        interval_seconds=max(
            0.0, float(os.environ.get("TREASUREIQ_SWEEP_INTERVAL_SECONDS", "120"))
        ),
        lavoratori=max(1, int(os.environ.get("TREASUREIQ_SWEEP_WORKERS", "6"))),
        delay=max(0.0, float(os.environ.get("TREASUREIQ_SWEEP_DELAY", "0"))),
        aderenza=os.environ.get("TREASUREIQ_SWEEP_ADERENZA", "0") == "1",
        once=once,
    )


def next_batch(config: WorkerConfig) -> list[str]:
    """Seleziona il prossimo lotto senza riesaminare i comuni di oggi."""

    oggi = datetime.now(timezone.utc).date()
    gia_fatti = _gia_registrati(config.db, oggi)
    candidati = [codice for codice in _comuni_da_censimento(config.db) if codice not in gia_fatti]
    return candidati[: config.batch_size]


def run_batch(config: WorkerConfig, comuni: list[str]) -> int:
    """Esegue un lotto riusando il CLI esistente."""

    if not comuni:
        return 0
    argv = [
        "sweep",
        *comuni,
        "--db",
        str(config.db),
        "--lavoratori",
        str(config.lavoratori),
        "--delay",
        str(config.delay),
    ]
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
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(config_from_env(db=args.db, once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
