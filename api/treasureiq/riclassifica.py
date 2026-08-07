"""Riconoscere una piattaforma in più, senza bussare a nessuno.

Ogni riga del censimento porta con sé l'impronta grezza del portale: nome del
server, estensioni delle rotte, prime directory degli asset. Quando impariamo
a riconoscere una famiglia nuova — perché qualcuno ha aperto un portale e ci
ha detto cosa c'era dentro — quella conoscenza si applica alle righe già
salvate leggendo l'impronta, invece di rifare un giro su ottomila comuni.

Le regole non stanno qui: stanno in `ingest.piattaforma.da_impronta`, le
stesse che la sonda applica durante lo sweep. Tenerle in un solo posto è il
punto: una copia in SQL diverge dalla copia in Python al primo caso strano, e
il censimento comincerebbe a contraddire se stesso a seconda di quando è
stata misurata una riga.

Le righe toccate restano marcate `classificato_da = 'riclassificazione'`.
Serve a `storico.evoluzione`, che deve poter distinguere un comune che ha
cambiato portale da un comune su cui abbiamo cambiato idea: contare il
secondo come il primo gonfierebbe proprio il numero che a questo progetto
farebbe più comodo che fosse vero.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from treasureiq.ingest.piattaforma import Piattaforma, da_impronta
from treasureiq.storico import DEFAULT_DB, apri


def proponi(db_path: Path, *, rilevato_il: date | None = None) -> list[tuple[str, str, str]]:
    """Cosa cambierebbe, senza cambiarlo: `(codice_istat, piattaforma, prova)`.

    Guarda solo chi è rimasto `IGNOTA`. Un portale che si era dichiarato ha
    già detto cosa è, e nessuna regola statistica deve poterlo smentire.
    """
    if not db_path.exists():
        return []
    dove = "piattaforma = ?"
    valori: list[object] = [Piattaforma.IGNOTA.value]
    if rilevato_il:
        dove += " AND rilevato_il = ?"
        valori.append(rilevato_il.isoformat())
    with apri(db_path) as conn:
        righe = conn.execute(
            f"SELECT codice_istat, rilevato_il, regione, impronta_grezza "
            f"FROM portale_snapshot WHERE {dove}",
            valori,
        ).fetchall()

    proposte: list[tuple[str, str, str]] = []
    for r in righe:
        firma = da_impronta(impronta=r["impronta_grezza"], regione=r["regione"])
        if firma is None:
            continue
        proposte.append((r["rilevato_il"], r["codice_istat"], firma.piattaforma.value))
    return proposte


def applica(db_path: Path, *, rilevato_il: date | None = None) -> Counter:
    """Scrive le riclassificazioni e restituisce quante per piattaforma."""
    conteggio: Counter = Counter()
    dove = "piattaforma = ?"
    valori: list[object] = [Piattaforma.IGNOTA.value]
    if rilevato_il:
        dove += " AND rilevato_il = ?"
        valori.append(rilevato_il.isoformat())

    with apri(db_path, scrittura=True) as conn:
        righe = conn.execute(
            f"SELECT codice_istat, rilevato_il, regione, impronta_grezza "
            f"FROM portale_snapshot WHERE {dove}",
            valori,
        ).fetchall()
        aggiornamenti = []
        for r in righe:
            firma = da_impronta(impronta=r["impronta_grezza"], regione=r["regione"])
            if firma is None:
                continue
            conteggio[firma.piattaforma.value] += 1
            aggiornamenti.append(
                (firma.piattaforma.value, firma.prova, r["rilevato_il"], r["codice_istat"])
            )
        conn.executemany(
            "UPDATE portale_snapshot SET piattaforma = ?, piattaforma_prova = ?, "
            "classificato_da = 'riclassificazione' "
            "WHERE rilevato_il = ? AND codice_istat = ?",
            aggiornamenti,
        )
        conn.commit()
    return conteggio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.riclassifica",
        description=(
            "Applica alle righe già censite le regole di riconoscimento imparate "
            "dopo lo sweep. Nessuna richiesta di rete."
        ),
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--data", help="Solo questo rilevamento (YYYY-MM-DD).")
    parser.add_argument(
        "--applica",
        action="store_true",
        help="Scrivi davvero. Senza, stampa soltanto cosa cambierebbe.",
    )
    args = parser.parse_args(argv)
    giorno = date.fromisoformat(args.data) if args.data else None

    if not args.applica:
        proposte = proponi(args.db, rilevato_il=giorno)
        for piattaforma, quanti in Counter(p for _, _, p in proposte).most_common():
            print(f"  {piattaforma:24} {quanti}")
        print(f"in tutto {len(proposte)} righe (prova: niente è stato scritto)")
        return 0

    conteggio = applica(args.db, rilevato_il=giorno)
    for piattaforma, quanti in conteggio.most_common():
        print(f"  {piattaforma:24} {quanti}")
    print(f"riclassificate {sum(conteggio.values())} righe in {args.db}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
