"""Ingestion CLI — refresh the committed snapshots from live sources.

Run with no arguments for a dry run that reports what would change without
writing anything, because the snapshots are committed artefacts and silently
rewriting them is how a demo stops matching the numbers quoted around it.

    python -m treasureiq.ingest --help
    python -m treasureiq.ingest --dry-run
    python -m treasureiq.ingest --write
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from treasureiq.ingest.wp_comuni import WPComuniConnector
from treasureiq.readiness import score_comune
from treasureiq.schema import Opportunity

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = REPO_ROOT / "data" / "seed"

#: Sources with a committed snapshot. Adding a comune here is the only change
#: needed to bring it into the demo, provided a connector can read it.
SOURCES = [
    {
        "codice_istat": "058003",
        "ente": "Comune di Albano Laziale",
        "base_url": "https://comune.albanolaziale.rm.it",
        "seed": "albano_058003.json",
        "connector": "wp_rest",
    },
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.ingest",
        description=(
            "Rilegge i servizi pubblicati dai comuni configurati e aggiorna gli "
            "snapshot in data/seed/. Senza --write non modifica nulla."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Scrive gli snapshot su disco. Senza questo flag è un dry run.",
    )
    parser.add_argument(
        "--comune",
        metavar="ISTAT",
        help="Limita l'esecuzione a un solo comune, per codice ISTAT.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Log di dettaglio."
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    sources = SOURCES
    if args.comune:
        sources = [s for s in SOURCES if s["codice_istat"] == args.comune]
        if not sources:
            print(f"Nessuna fonte configurata per il comune {args.comune}.", file=sys.stderr)
            return 2

    exit_code = 0
    for source in sources:
        print(f"\n{source['ente']} ({source['codice_istat']})")
        try:
            with WPComuniConnector(
                base_url=source["base_url"],
                ente=source["ente"],
                codice_istat=source["codice_istat"],
            ) as connector:
                records = connector.fetch()
        except Exception as exc:
            # One unreachable source must not abort the others: a partial
            # refresh with a clear failure beats an all-or-nothing run.
            print(f"  fonte non raggiungibile: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        stats = connector.stats
        print(f"  letti {stats.records_seen}, normalizzati {stats.records_emitted}")
        if stats.errors:
            print(f"  {len(stats.errors)} record scartati")
            exit_code = 1

        report = score_comune(
            ente=source["ente"],
            codice_istat=source["codice_istat"],
            records=records,
        )
        print(f"  readiness {report.score}/100 ({report.grade.value})")

        path = SEED_DIR / source["seed"]
        payload = [json.loads(r.model_dump_json()) for r in records]
        new_text = json.dumps(payload, ensure_ascii=False, indent=1)

        if path.exists():
            old = json.loads(path.read_text("utf-8"))
            old_ids = {o["id"] for o in old}
            new_ids = {o["id"] for o in payload}
            added, removed = new_ids - old_ids, old_ids - new_ids
            changed = _changed_hashes(old, payload)
            if not (added or removed or changed):
                print("  snapshot già aggiornato")
                continue
            print(
                f"  differenze: +{len(added)} nuovi, -{len(removed)} rimossi, "
                f"{len(changed)} modificati"
            )
        else:
            print(f"  snapshot assente: {len(payload)} record da scrivere")

        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
            print(f"  scritto {path.relative_to(REPO_ROOT)}")
        else:
            print("  dry run: nulla è stato scritto (usa --write per applicare)")

    return exit_code


def _changed_hashes(old: list[dict], new: list[dict]) -> set[str]:
    """IDs whose upstream payload hash moved — i.e. the comune edited them."""
    old_hashes = {o["id"]: o.get("source", {}).get("raw_hash") for o in old}
    return {
        o["id"]
        for o in new
        if o["id"] in old_hashes
        and o.get("source", {}).get("raw_hash") != old_hashes[o["id"]]
    }


if __name__ == "__main__":
    raise SystemExit(run())
