"""Read-only reader for the promoted flat service catalog (``data/catalog/{istat}.json``).

The national service catalog is an AUTHORITATIVE, versioned artifact: a curated
promotion of confirmed ``ServiceReference`` entries, one file per municipality,
keyed by ``ServiceKey`` value (schema ``{municipality_istat, services}``).  It is
NOT a TTL cache — it stays valid until the next promotion replaces it, so it
carries no freshness policy of its own.

The resolver consults it AFTER a fresh ``service_cache`` hit and BEFORE any live
connector call (``cache fresca → catalogo flat → live``).  This module only
reads: a missing file, an absent key, or a malformed entry all return ``None`` so
the resolver falls back cleanly to the live connector.  It NEVER writes — in
production ``/data`` is mounted read-only and this code opens no write path.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from pydantic import ValidationError

from treasureiq.catalog.service_contracts import ServiceKey, ServiceReference

logger = logging.getLogger(__name__)

#: ``parents[2]`` from ``treasureiq/catalog/service_catalog.py`` → the ``api/``
#: root, matching ``api.REPO_ROOT``/``api.DATA_DIR`` so the reader resolves the
#: same catalog directory the running app mounts.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Mirrors ``service_cache``'s filesystem boundary (kept local, not imported, so
#: this read-only module owns its own guard): ``source_id`` reaches a path, so
#: anything but a safe single component is rejected — never sanitised silently.
_RE_SOURCE_ID_SICURO = re.compile(r"[A-Za-z0-9_-]+")


def catalog_dir() -> Path:
    """The flat catalog root, re-read from the env each call (test-friendly)."""
    base = Path(os.environ.get("TREASUREIQ_DATA_DIR", REPO_ROOT / "data"))
    return base / "catalog"


def _percorso(source_id: str, base: Path) -> Path | None:
    """``{base}/{source_id}.json`` if ``source_id`` is a safe component, else ``None``."""
    if not _RE_SOURCE_ID_SICURO.fullmatch(source_id):
        return None
    return base / f"{source_id}.json"


def carica(
    source_id: str,
    service_key: ServiceKey,
    *,
    base: Path | None = None,
) -> ServiceReference | None:
    """Return the promoted ``ServiceReference`` for ``(source_id, service_key)``.

    Read-only lookup in ``{base}/{source_id}.json``.  Returns ``None`` — a clean
    signal for the resolver to fall back to the live connector — when the file is
    missing or unreadable, the ``service_key`` is absent, or the stored entry
    fails ``ServiceReference`` validation.  Only the requested key is validated,
    so one malformed sibling entry never blocks a valid key.
    """
    root = base if base is not None else catalog_dir()
    percorso = _percorso(source_id, root)
    if percorso is None or not percorso.is_file():
        return None
    try:
        contenuto = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("catalogo servizi illeggibile %s: %s", percorso, exc)
        return None
    if not isinstance(contenuto, dict):
        return None
    services = contenuto.get("services")
    if not isinstance(services, dict):
        return None
    grezzo = services.get(service_key.value)
    if grezzo is None:
        return None
    try:
        return ServiceReference.model_validate(grezzo)
    except ValidationError as exc:
        logger.warning(
            "voce catalogo %s/%s non valida: %s",
            source_id,
            service_key.value,
            exc,
        )
        return None
