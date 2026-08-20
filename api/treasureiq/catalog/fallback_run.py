"""Explicit backoffice execution of the indirect fallback."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from treasureiq.catalog.data_contracts import DataBatch, FreshnessPolicy, RequestLimits
from treasureiq.catalog.runtime import CatalogRuntime
from treasureiq.mappa_connettore import MappaConnettore, mappa_connettore


class FallbackRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    platform_id: str = Field(min_length=1)
    started_at: datetime
    batches: tuple[DataBatch, ...]


def run_fallback(
    mappa: MappaConnettore,
    *,
    platform_id: str,
    run_id: str,
    runtime: CatalogRuntime | None = None,
) -> FallbackRun:
    started_at = datetime.now(timezone.utc)
    batches = (runtime or CatalogRuntime()).execute_fallbacks(
        source_id=mappa.codice_istat,
        platform_id=platform_id,
        mappa=mappa,
        freshness=FreshnessPolicy(max_age_seconds=86400),
        limits=RequestLimits(),
        manifest_revision=1,
        request_prefix=run_id,
    )
    return FallbackRun(
        run_id=run_id,
        source_id=mappa.codice_istat,
        platform_id=platform_id,
        started_at=started_at,
        batches=batches,
    )


def load_mappa(
    *,
    mappa_json: Path | None = None,
    scansione_json: Path | None = None,
    codice_istat: str | None = None,
    usa_cache: bool = True,
) -> MappaConnettore:
    sources = (mappa_json, scansione_json, codice_istat)
    if sum(source is not None for source in sources) != 1:
        raise ValueError("specificare esattamente una fonte per la mappa")
    if mappa_json is not None:
        return MappaConnettore.model_validate_json(mappa_json.read_text(encoding="utf-8"))
    if scansione_json is not None:
        payload = json.loads(scansione_json.read_text(encoding="utf-8"))
        return MappaConnettore.model_validate(payload.get("mappa", payload))
    mappa = mappa_connettore(codice_istat, usa_cache=usa_cache)
    if mappa is None:
        raise ValueError(f"mappa non disponibile per {codice_istat}")
    return mappa


def main() -> int:
    parser = argparse.ArgumentParser(description="Esegui il fallback indiretto TIQ")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mappa-json", type=Path)
    source.add_argument("--scansione-json", type=Path)
    source.add_argument("--istat")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--platform-id")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()

    mappa = load_mappa(
        mappa_json=args.mappa_json,
        scansione_json=args.scansione_json,
        codice_istat=args.istat,
        usa_cache=not args.no_cache,
    )
    platform_id = args.platform_id or mappa.piattaforma_id or "unknown"
    result = run_fallback(mappa, platform_id=platform_id, run_id=args.run_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(args.output)
    if args.store is not None:
        from treasureiq.catalog.fallback_store import FallbackRunStore

        FallbackRunStore(args.store).save(result)
    print(json.dumps({"run_id": result.run_id, "batches": len(result.batches)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
