"""A dated record of what each comune has cost us, kept over time.

Usage:
    python -m treasureiq.storico [--db data/storico.db]

Everything else in this project reports the present: what a comune publishes
today, what it costs today. That is enough to state a fact and not enough to
show a change, and a change is the only thing that would tell an
administration whether opening their data actually did anything. So each
ingestion writes one dated row per comune and leaves it there.

Written at ingestion, read at runtime. The API container mounts `data/`
read-only, which SQLite is content with for reads and which keeps the property
the rest of the system relies on: a citizen's question never writes anything,
so two people asking the same thing cannot get different answers.

One row per comune per day, replaced if the day is run twice. Two ingestions
on the same afternoon are not two observations of the world — treating them as
two points would put a slope in a chart that only measured how often we
happened to run the job.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from treasureiq.costo import CostoComune, costo_comune
from treasureiq.integration import load_enti
from treasureiq.schema import Livello, Opportunity

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("data/storico.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS costo_snapshot (
    rilevato_il          TEXT    NOT NULL,
    codice_istat         TEXT    NOT NULL,
    ente                 TEXT    NOT NULL,
    modo                 TEXT    NOT NULL,
    record_totali        INTEGER NOT NULL,
    record_strutturati   INTEGER NOT NULL,
    record_recuperati    INTEGER NOT NULL,
    record_non_recuperati INTEGER NOT NULL,
    costo_totale         REAL    NOT NULL,
    costo_per_record     REAL,
    scoperta_il          TEXT    NOT NULL,
    scoperta_scaduta     INTEGER NOT NULL,
    secondi_recupero     REAL,
    PRIMARY KEY (rilevato_il, codice_istat)
);
"""


@dataclass
class PuntoStorico:
    rilevato_il: date
    codice_istat: str
    ente: str
    modo: str
    record_totali: int
    record_strutturati: int
    record_recuperati: int
    record_non_recuperati: int
    costo_totale: float
    costo_per_record: float | None
    scoperta_scaduta: bool


def apri(db_path: Path, *, scrittura: bool = False) -> sqlite3.Connection:
    """Open the store, read-only unless writing is explicitly asked for.

    The read path opens through a `file:...?mode=ro` URI rather than trusting
    the caller: at runtime `data/` is mounted read-only anyway, and a
    connection that cannot write is a cheaper guarantee than a convention that
    it will not.
    """
    if scrittura:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA)
        return conn
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def registra(conn: sqlite3.Connection, costo: CostoComune, *, oggi: date) -> None:
    """Write today's row for one comune, replacing any earlier run today."""
    conn.execute(
        """
        INSERT INTO costo_snapshot (
            rilevato_il, codice_istat, ente, modo,
            record_totali, record_strutturati, record_recuperati,
            record_non_recuperati, costo_totale, costo_per_record,
            scoperta_il, scoperta_scaduta, secondi_recupero
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(rilevato_il, codice_istat) DO UPDATE SET
            ente=excluded.ente, modo=excluded.modo,
            record_totali=excluded.record_totali,
            record_strutturati=excluded.record_strutturati,
            record_recuperati=excluded.record_recuperati,
            record_non_recuperati=excluded.record_non_recuperati,
            costo_totale=excluded.costo_totale,
            costo_per_record=excluded.costo_per_record,
            scoperta_il=excluded.scoperta_il,
            scoperta_scaduta=excluded.scoperta_scaduta,
            secondi_recupero=excluded.secondi_recupero
        """,
        (
            oggi.isoformat(),
            costo.codice_istat,
            costo.ente,
            costo.modo.value,
            costo.record_totali,
            costo.record_strutturati,
            costo.record_recuperati_da_prosa,
            costo.record_non_recuperati,
            costo.costo_totale,
            costo.costo_per_record,
            costo.scoperta_il.isoformat(),
            int(costo.scoperta_scaduta),
            costo.secondi_recupero,
        ),
    )


def serie(db_path: Path, *, codice_istat: str | None = None) -> list[PuntoStorico]:
    """Every recorded point, oldest first. Empty when the store does not exist.

    A missing file is the ordinary state before the first ingestion, not an
    error: the pages that read this have to render on a fresh checkout, and a
    chart with no points is the honest picture of a history nobody has
    recorded yet.
    """
    if not db_path.exists():
        return []
    with apri(db_path) as conn:
        sql = "SELECT * FROM costo_snapshot"
        params: tuple[str, ...] = ()
        if codice_istat:
            sql += " WHERE codice_istat = ?"
            params = (codice_istat,)
        sql += " ORDER BY rilevato_il ASC, ente ASC"
        righe = conn.execute(sql, params).fetchall()
    return [
        PuntoStorico(
            rilevato_il=date.fromisoformat(r["rilevato_il"]),
            codice_istat=r["codice_istat"],
            ente=r["ente"],
            modo=r["modo"],
            record_totali=r["record_totali"],
            record_strutturati=r["record_strutturati"],
            record_recuperati=r["record_recuperati"],
            record_non_recuperati=r["record_non_recuperati"],
            costo_totale=r["costo_totale"],
            costo_per_record=r["costo_per_record"],
            scoperta_scaduta=bool(r["scoperta_scaduta"]),
        )
        for r in righe
    ]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--seed-dir", default="data/seed")
    args = p.parse_args(argv)

    oggi = date.today()
    enti = load_enti()
    seed_dir = Path(args.seed_dir)
    db_path = Path(args.db)

    scritti = 0
    with apri(db_path, scrittura=True) as conn:
        for percorso in sorted(seed_dir.glob("*.json")):
            dati = json.loads(percorso.read_text("utf-8"))
            if not dati:
                continue
            istat = dati[0].get("source", {}).get("ente_codice_istat")
            ente = enti.get(istat) if istat else None
            if ente is None:
                logger.info("salto %s: nessun ente con codice %s", percorso.name, istat)
                continue
            records = [Opportunity.model_validate(x) for x in dati]
            records = [r for r in records if r.livello is Livello.COMUNALE]
            c = costo_comune(ente=ente, records=records, oggi=oggi)
            registra(conn, c, oggi=oggi)
            scritti += 1
            logger.info(
                "%-26s costo %.1f (%.2f/record) su %d record",
                c.ente,
                c.costo_totale,
                c.costo_per_record or 0,
                c.record_totali,
            )
        conn.commit()

    punti = serie(db_path)
    giorni = sorted({p.rilevato_il for p in punti})
    logger.info(
        "scritti %d comuni in %s — %d punti su %d giorni distinti",
        scritti,
        db_path,
        len(punti),
        len(giorni),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
