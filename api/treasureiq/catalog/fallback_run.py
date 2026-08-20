"""Explicit backoffice execution of the indirect fallback."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from treasureiq.catalog.data_contracts import DataBatch, FreshnessPolicy, RequestLimits
from treasureiq.catalog.runtime import CatalogRuntime
from treasureiq.mappa_connettore import MappaConnettore


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Esegui il fallback indiretto TIQ")
    parser.add_argument("--mappa-json", type=Path, required=True)
    parser.add_argument("--platform-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    mappa = MappaConnettore.model_validate_json(args.mappa_json.read_text(encoding="utf-8"))
    result = run_fallback(mappa, platform_id=args.platform_id, run_id=args.run_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"run_id": result.run_id, "batches": len(result.batches)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
