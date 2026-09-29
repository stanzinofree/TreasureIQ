"""Aggregated, honest counters for the operational monitoring dashboard.

This module answers one question the old `/api/status` view could not: *where
does each layer of TreasureIQ's data actually stand today?* It reads only
aggregate counts and operational metadata — never the content of a comune's
records, never a conversation — and it never probes a live site.

Three data layers, kept strictly apart because a reader who conflates them
draws the wrong conclusion:

  - **Demo curata** — the handful of MVP comuni in `data/seed`, deep
    LLM-extracted opportunities. Static, hand-updated. This is a proof the
    method works, not national coverage.
  - **Copertura nazionale** — the shallow service maps in `data/catalog`
    (~2.9k comuni of ~7.9k). Which platform each runs, and whether that
    platform has a refresh reader at all.
  - **Refresh operativo** — the continuous refresh of *already initialised*
    comuni (`data-live`). Freshness, not discovery: it re-reads comuni that
    already have a connettore record, it does not enrol new ones.

The refresh section deliberately does NOT derive its health from the seed's
ingestion timestamp (the false-negative the old `Sistemi` view showed): a
stale seed says nothing about whether the refresh worker is running.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from treasureiq.bootstrap import PIATTAFORME_CATALOGO_REFRESH

logger = logging.getLogger(__name__)

#: Oltre questa età lo stato del worker è considerato "fermo": il sidecar viene
#: riscritto a ogni batch, quindi un file più vecchio dell'intervallo continuo
#: più un margine significa che nessun batch è passato di recente.
WORKER_STALE_SECONDS = 30 * 60


# --------------------------------------------------------------------------- #
# Output contract
# --------------------------------------------------------------------------- #
class DemoCurataOut(BaseModel):
    comuni: int
    record_totali: int
    curato_nazionale: int
    aggiornato_il: str | None


class PiattaformaCopertura(BaseModel):
    piattaforma: str
    comuni: int
    eleggibile: bool


class CoperturaOut(BaseModel):
    universo: int
    catalogati: int
    eleggibili: int
    non_eleggibili: int
    per_piattaforma: list[PiattaformaCopertura]


class UltimoBatch(BaseModel):
    avviato_il: str | None = None
    durata_s: float | None = None
    comuni: int | None = None
    tentati: int | None = None
    riusciti: int | None = None
    falliti: int | None = None
    senza_contratto: int | None = None
    eventi_429: int | None = None
    domini_bloccati: int | None = None
    codice: int | None = None


class RefreshOperativoOut(BaseModel):
    eleggibili: int
    inizializzati: int  # eligible AND initialised (intersection, not file count)
    mai_inizializzati: int
    fuori_perimetro: int  # data-live records outside the eligible set (demo, pilot)
    ultimo_refresh: str | None
    worker_stato: str  # "attivo" | "fermo" | "sconosciuto"
    sidecar_aggiornato_il: str | None
    ultimo_batch: UltimoBatch | None


class ComponenteOut(BaseModel):
    nome: str
    stato: str  # "ok" | "degraded" | "down" | "unknown"
    detail: str


class MonitoraggioOut(BaseModel):
    demo: DemoCurataOut
    copertura: CoperturaOut
    refresh: RefreshOperativoOut
    sistemi: list[ComponenteOut]


# --------------------------------------------------------------------------- #
# Helpers — all read-only, all aggregate
# --------------------------------------------------------------------------- #
def _piattaforma_del_file(payload: dict) -> str | None:
    """Dominant provider platform of one catalog file, or None.

    Catalog files are homogeneous per comune (one platform), but a stray
    service can carry a different `provider_platform`; take the most common so a
    single outlier never reclassifies the comune.
    """
    servizi = payload.get("services") or {}
    if not isinstance(servizi, dict):
        return None
    conteggio: Counter[str] = Counter()
    for servizio in servizi.values():
        if isinstance(servizio, dict):
            plat = servizio.get("provider_platform")
            if plat:
                conteggio[str(plat)] += 1
    if not conteggio:
        return None
    return conteggio.most_common(1)[0][0]


@lru_cache(maxsize=8)
def _aggrega_catalogo(catalog_dir: str) -> tuple[int, tuple[tuple[str, int], ...]]:
    """(catalogati, per-platform counts). Cached: the catalog is frozen on disk.

    Only top-level `*.json` files are comuni; the `municipality/` measurement
    store lives in a subdirectory and is skipped by the non-recursive glob.
    """
    root = Path(catalog_dir)
    per_piattaforma: Counter[str] = Counter()
    catalogati = 0
    if not root.exists():
        return 0, ()
    for percorso in root.glob("*.json"):
        try:
            payload = json.loads(percorso.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        catalogati += 1
        plat = _piattaforma_del_file(payload)
        per_piattaforma[plat or "sconosciuta"] += 1
    return catalogati, tuple(sorted(per_piattaforma.items(), key=lambda kv: (-kv[1], kv[0])))


@lru_cache(maxsize=8)
def _codici_eleggibili(catalog_dir: str) -> frozenset[str]:
    """ISTAT codes of catalogued comuni on a refresh-capable platform.

    The refresh perimeter, as a set of codes (not just a count): the caller
    intersects it with the initialised comuni so "inizializzati" means *eligible
    and initialised*, never a raw connettore file count. Cached; catalog frozen.
    """
    root = Path(catalog_dir)
    codici: set[str] = set()
    if not root.exists():
        return frozenset()
    for percorso in root.glob("*.json"):
        try:
            payload = json.loads(percorso.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _piattaforma_del_file(payload) in PIATTAFORME_CATALOGO_REFRESH:
            codici.add(percorso.stem)
    return frozenset(codici)


@lru_cache(maxsize=8)
def _universo(comuni_istat_path: str) -> int:
    """Count of all Italian comuni (ISTAT ∪ IPA). Cached; static file."""
    try:
        dati = json.loads(Path(comuni_istat_path).read_text("utf-8"))
        return len(dati)
    except (OSError, json.JSONDecodeError, TypeError):
        return 0


def _parse_iso(valore: object) -> datetime | None:
    if not isinstance(valore, str) or not valore:
        return None
    try:
        dato = datetime.fromisoformat(valore.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dato if dato.tzinfo else dato.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #
def _demo(seed_dir: Path, curated_name: str) -> DemoCurataOut:
    comuni = 0
    record_totali = 0
    curato_nazionale = 0
    ultimo: datetime | None = None
    if seed_dir.exists():
        for percorso in sorted(seed_dir.glob("*.json")):
            try:
                dati = json.loads(percorso.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(dati, list):
                continue
            if percorso.name == curated_name:
                curato_nazionale = len(dati)
                continue
            comuni += 1
            record_totali += len(dati)
            for record in dati:
                fetched = _parse_iso((record.get("source") or {}).get("fetched_at"))
                if fetched and (ultimo is None or fetched > ultimo):
                    ultimo = fetched
    return DemoCurataOut(
        comuni=comuni,
        record_totali=record_totali,
        curato_nazionale=curato_nazionale,
        aggiornato_il=ultimo.isoformat() if ultimo else None,
    )


def _copertura(catalog_dir: Path, comuni_istat_path: Path) -> CoperturaOut:
    catalogati, per_piattaforma = _aggrega_catalogo(str(catalog_dir))
    righe: list[PiattaformaCopertura] = []
    eleggibili = 0
    for piattaforma, conteggio in per_piattaforma:
        eleggibile = piattaforma in PIATTAFORME_CATALOGO_REFRESH
        if eleggibile:
            eleggibili += conteggio
        righe.append(
            PiattaformaCopertura(
                piattaforma=piattaforma, comuni=conteggio, eleggibile=eleggibile
            )
        )
    return CoperturaOut(
        universo=_universo(str(comuni_istat_path)),
        catalogati=catalogati,
        eleggibili=eleggibili,
        non_eleggibili=catalogati - eleggibili,
        per_piattaforma=righe,
    )


def _stato_worker(sidecar: dict | None, aggiornato: datetime | None) -> str:
    if sidecar is None or aggiornato is None:
        return "sconosciuto"
    eta = (datetime.now(timezone.utc) - aggiornato).total_seconds()
    return "attivo" if eta <= WORKER_STALE_SECONDS else "fermo"


def _refresh(live_dir: Path, eleggibili_codici: frozenset[str]) -> RefreshOperativoOut:
    eleggibili = len(eleggibili_codici)
    conn_dir = live_dir / "connettore"
    inizializzati = 0     # eligible comuni that already hold a data-live record
    fuori_perimetro = 0   # records outside the eligible set (demo, pilot, non-refresh)
    ultimo: datetime | None = None
    if conn_dir.exists():
        for percorso in conn_dir.glob("*.json"):
            if percorso.stem in eleggibili_codici:
                inizializzati += 1
            else:
                fuori_perimetro += 1
            try:
                record = json.loads(percorso.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            letto = _parse_iso(record.get("letto_il") or record.get("controllato_il"))
            if letto and (ultimo is None or letto > ultimo):
                ultimo = letto

    sidecar: dict | None = None
    sidecar_path = live_dir / "_worker_status.json"
    if sidecar_path.exists():
        try:
            sidecar = json.loads(sidecar_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            sidecar = None

    aggiornato = _parse_iso((sidecar or {}).get("aggiornato_il")) if sidecar else None
    ultimo_batch = None
    if sidecar and isinstance(sidecar.get("ultimo_batch"), dict):
        ultimo_batch = UltimoBatch(**{
            k: v for k, v in sidecar["ultimo_batch"].items()
            if k in UltimoBatch.model_fields
        })

    return RefreshOperativoOut(
        eleggibili=eleggibili,
        inizializzati=inizializzati,
        mai_inizializzati=max(0, eleggibili - inizializzati),
        fuori_perimetro=fuori_perimetro,
        ultimo_refresh=ultimo.isoformat() if ultimo else None,
        worker_stato=_stato_worker(sidecar, aggiornato),
        sidecar_aggiornato_il=aggiornato.isoformat() if aggiornato else None,
        ultimo_batch=ultimo_batch,
    )


def _sistemi(
    demo: DemoCurataOut, copertura: CoperturaOut, refresh: RefreshOperativoOut
) -> list[ComponenteOut]:
    """Component health from real signals only — never from seed freshness."""
    stato_worker = {
        "attivo": ("ok", "il refresh continuo ha completato un batch di recente"),
        "fermo": ("degraded", "nessun batch di refresh recente: worker fermo o sospeso"),
        "sconosciuto": ("unknown", "nessuno stato worker registrato"),
    }[refresh.worker_stato]
    return [
        ComponenteOut(
            nome="Demo curata",
            stato="ok" if demo.comuni > 0 else "down",
            detail=f"{demo.comuni} comuni MVP, {demo.record_totali} record in archivio",
        ),
        ComponenteOut(
            nome="Copertura nazionale",
            stato="ok" if copertura.catalogati > 0 else "down",
            detail=(
                f"{copertura.catalogati} comuni catalogati su {copertura.universo}, "
                f"{copertura.eleggibili} eleggibili al refresh"
            ),
        ),
        ComponenteOut(
            nome="Refresh continuo",
            stato=stato_worker[0],
            detail=stato_worker[1],
        ),
    ]


def build_monitoraggio(
    *,
    catalog_dir: Path,
    seed_dir: Path,
    live_dir: Path,
    comuni_istat_path: Path,
    curated_name: str,
) -> MonitoraggioOut:
    """Assemble the four monitoring sections from disk, aggregate-only."""
    demo = _demo(seed_dir, curated_name)
    copertura = _copertura(catalog_dir, comuni_istat_path)
    refresh = _refresh(live_dir, _codici_eleggibili(str(catalog_dir)))
    return MonitoraggioOut(
        demo=demo,
        copertura=copertura,
        refresh=refresh,
        sistemi=_sistemi(demo, copertura, refresh),
    )
