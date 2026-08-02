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

from treasureiq.extract.llm import load_extractor
from treasureiq.ingest.wp_comuni import WPComuniConnector
from treasureiq.ingest.wp_pages import WPPagesConnector
from treasureiq.readiness import score_comune
from treasureiq.schema import Opportunity

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = REPO_ROOT / "data" / "seed"

#: D-15 budget knob: how many candidate `pages` the six keyword searches may
#: surface before the content filter and the LLM extractor ever run. Bounds
#: total ingestion wall-clock (each extracted page costs ~10-60s depending on
#: how many PDF attachments it links; see `.kapi/spike-d07.md`).
PAGES_MAX_CANDIDATES = 15

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
    {
        # Comparator (D-18). Of the 119 comuni in the province of Rome, 20 expose
        # a working /servizi API; Fonte Nuova ranks 1st with 34, Albano 2nd with
        # 32, and the two are close in size (~35k vs ~41k residents). Two measured
        # comuni make the recovery-cost metric comparative instead of absolute.
        "codice_istat": "058122",
        "ente": "Comune di Fonte Nuova",
        "base_url": "https://comune.fontenuova.rm.it",
        "seed": "fontenuova_058122.json",
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
        print(f"  servizi: letti {stats.records_seen}, normalizzati {stats.records_emitted}")
        if stats.errors:
            print(f"  servizi: {len(stats.errors)} record scartati")
            exit_code = 1

        # D-03/D-15: bandi/concorsi/volontariato live as prose `pages`, not
        # typed `servizi`. Ingested by a second connector, quote-gated
        # through the LLM extractor, then merged below — never abort the
        # whole comune if this leg fails, the servizi records still stand.
        try:
            extractor = load_extractor()
            with WPPagesConnector(
                base_url=source["base_url"],
                ente=source["ente"],
                codice_istat=source["codice_istat"],
                extractor=extractor,
                max_pages=PAGES_MAX_CANDIDATES,
            ) as pages_connector:
                page_records = pages_connector.fetch()
            pages_stats = pages_connector.stats
            print(
                f"  pagine: lette {pages_stats.records_seen}, "
                f"normalizzate {pages_stats.records_emitted}, "
                f"scartate dal filtro {len(pages_connector.dropped)}"
            )
            if pages_stats.errors:
                print(f"  pagine: {len(pages_stats.errors)} record scartati")
                exit_code = 1
            if args.verbose:
                print(f"  pagine: {extractor.report()}")
                for line in pages_connector.dropped:
                    print(f"    scartata: {line}")
        except Exception as exc:
            print(f"  pagine non raggiungibili: {exc}", file=sys.stderr)
            exit_code = 1
            page_records = []

        records = _merge_pages_into_servizi(records, page_records)

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


def _normalise_source_url(url: str) -> str:
    """Comparable key for dedup: case and trailing slash must not create a false split."""
    return str(url).strip().rstrip("/").lower()


def _merge_pages_into_servizi(
    servizi: list[Opportunity], pages: list[Opportunity]
) -> list[Opportunity]:
    """One seed per comune: `pages` records that duplicate a `servizio` are dropped.

    Dedup key is the normalised `source.url` (DISCRETION, `.kapi/spec.md`):
    the same municipal notice can appear as both a typed `servizio` and a
    prose `page` when its content overlaps both post types. The `servizio`
    wins because it carries richer typed fields (R-5) — the `page` record,
    and everything the LLM extracted from it, is discarded in that case.
    """
    servizi_urls = {_normalise_source_url(o.source.url) for o in servizi}
    merged = list(servizi)
    dropped = 0
    for page in pages:
        if _normalise_source_url(page.source.url) in servizi_urls:
            dropped += 1
            continue
        merged.append(page)
    if dropped:
        print(f"  pagine: {dropped} scartate come duplicati di un servizio già tipizzato")
    return merged


def _changed_hashes(old: list[dict], new: list[dict]) -> set[str]:
    """IDs whose full record changed relative to the committed snapshot.

    Started as an upstream-hash-only comparison, but that missed a real case:
    D-16 added recovery-cost instrumentation fields computed by *our* own
    ingestion code, not the comune's. Those can change (or appear for the
    first time) with `source.raw_hash` completely unchanged, since the
    upstream WP payload never moved. Comparing the full record — not just the
    hash — is what makes a same-source, different-instrumentation run
    register as a real diff instead of silently being skipped as "già
    aggiornato".
    """
    old_by_id = {o["id"]: o for o in old}
    return {
        o["id"]
        for o in new
        if o["id"] in old_by_id and old_by_id[o["id"]] != o
    }


if __name__ == "__main__":
    raise SystemExit(run())
