"""On-disk cache of resolved ``ServiceReference`` entries (Ramo 3, Slice 2).

A fresh cache-hit answers a service request with no network; a miss/stale/
version-mismatch returns ``None`` — the signal the dispatcher (Slice 5) uses to
run the live connector (Slice 3).  This module is the store only: no network,
no connector, no chat wiring here.

Twin of ``mappa_connettore._da_cache``/``_in_cache`` and
``service_portal_connector._inventory_from_live``: same ``LIVE_DIR`` mount, same
discipline — a corrupt or absent file is a miss (never a crash), an absent mount
degrades to a warning instead of failing the request.  It is a FOURTH store,
distinct from the SP inventory, curated seed and websearch cache.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from treasureiq.catalog.contracts import FreshnessStatus
from treasureiq.catalog.data_contracts import FreshnessPolicy
from treasureiq.catalog.freshness import freshness_da_datetime
from treasureiq.catalog.service_contracts import (
    SERVICE_CACHE_SCHEMA_VERSION,
    CachedService,
    ServiceCacheFile,
    ServiceKey,
    ServiceReference,
)
from treasureiq.sonda_live import LIVE_DIR

logger = logging.getLogger(__name__)

#: A ``source_id`` may only name a single path component: ISTAT-style codes and
#: safe identifiers, never a path separator or ``..``.  This is a security
#: boundary — ``source_id`` reaches the filesystem, so a traversal attempt is
#: rejected here rather than sanitised silently.
_RE_SOURCE_ID_SICURO = re.compile(r"[A-Za-z0-9_-]+")


def _componente_sicuro(source_id: str) -> str:
    """Return ``source_id`` if it is a safe single path component, else raise.

    Rejects empty strings, path separators (``/`` ``\\``), ``..`` traversal and
    any character outside the safe set — a hardened guard against a crafted
    ``source_id`` escaping ``LIVE_DIR``.
    """
    if not _RE_SOURCE_ID_SICURO.fullmatch(source_id):
        raise ValueError(f"source_id non valido per il filesystem: {source_id!r}")
    return source_id


def _percorso(source_id: str) -> Path:
    return LIVE_DIR / "servizi-risolti" / f"{_componente_sicuro(source_id)}.json"


def _carica_file(source_id: str) -> ServiceCacheFile | None:
    """Read the whole cache file for a source; corrupt/absent → ``None``."""
    percorso = _percorso(source_id)
    if not percorso.exists():
        return None
    try:
        contenuto = ServiceCacheFile.model_validate_json(percorso.read_text("utf-8"))
    except Exception:  # noqa: BLE001 — una cache illeggibile è una cache assente
        logger.warning("cache servizi illeggibile: %s", percorso)
        return None
    # Il nome-file è la chiave: un file il cui `source_id` interno non combacia
    # è incoerente (rinominato/copiato a mano) e non deve contaminare un altro
    # comune — miss, come una cache corrotta.
    if contenuto.source_id != source_id:
        logger.warning("cache servizi con source_id incoerente: %s", percorso)
        return None
    return contenuto


def carica(
    source_id: str, service_key: ServiceKey, *, policy: FreshnessPolicy
) -> ServiceReference | None:
    """Fresh cache-hit → ``ServiceReference``; miss/stale/version-mismatch → ``None``.

    A hit requires: the entry exists, its ``schema_version`` equals the current
    ``SERVICE_CACHE_SCHEMA_VERSION`` (older AND future versions are not safely
    readable → miss), and its age is within ``policy.max_age_seconds``.  No
    network here: disk read only.  An invalid ``source_id`` raises.
    """
    contenuto = _carica_file(source_id)
    if contenuto is None:
        return None
    voce = next((e for e in contenuto.entries if e.service_key is service_key), None)
    if voce is None:
        return None
    if voce.schema_version != SERVICE_CACHE_SCHEMA_VERSION:
        return None
    fresh = freshness_da_datetime(voce.retrieved_at, policy.max_age_seconds)
    if fresh.status is not FreshnessStatus.FRESH:
        return None
    return voce.reference


def salva(source_id: str, service_key: ServiceKey, reference: ServiceReference) -> None:
    """Atomically upsert one ``service_key`` entry, preserving the others.

    Writes to a ``.tmp`` sibling then ``replace()`` so a concurrent reader sees
    the old file or the new one, never a half-written file.  An absent/unwritable
    mount degrades to a warning (the caller already holds the reference).  An
    invalid ``source_id`` raises before any filesystem access.
    """
    percorso = _percorso(source_id)
    now = datetime.now(timezone.utc)
    esistente = _carica_file(source_id)
    altre = tuple(
        e for e in (esistente.entries if esistente else ()) if e.service_key is not service_key
    )
    nuova = CachedService(service_key=service_key, reference=reference, retrieved_at=now)
    contenuto = ServiceCacheFile(source_id=source_id, entries=altre + (nuova,), updated_at=now)
    provvisorio = percorso.with_suffix(".tmp")
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio.write_text(contenuto.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("cache servizi non scrivibile (%s): %s", percorso, exc)
        # write_text può riuscire e replace fallire: non lasciare un .tmp orfano.
        try:
            provvisorio.unlink(missing_ok=True)
        except OSError:
            pass
