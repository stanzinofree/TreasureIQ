"""Selection logic for the connettore bootstrap (canary-first enrolment).

Pure and side-effect-free: this module only *decides* which eligible,
uninitialised comuni to initialise and in what order. Fetching, checkpointing
and the stop-file belong to the CLI (`registro_cli bootstrap`); keeping the
selection here makes it exhaustively testable without touching the network.

A comune is a bootstrap candidate when all three hold:
  1. it is catalogued on a refresh-capable platform (``PIATTAFORME_REFRESH``);
  2. it is actually in the censimento queue the refresh worker reads
     (``portale_snapshot`` on a ``_LEGGIBILI`` platform) — so that once
     initialised, the ordinary refresh will pick it up;
  3. it has no data-live connettore record yet (never initialised).

The recon showed (1) ⊆ (2) today, but intersecting explicitly guards against
catalog/queue drift: we never bootstrap a comune the refresh loop would then
ignore.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from treasureiq.connettore import PIATTAFORME_REFRESH

# Il catalogo servizi chiama entrambe le varianti WP del censimento "wordpress_agid".
PIATTAFORME_CATALOGO_REFRESH = PIATTAFORME_REFRESH | {"wordpress_agid"}


def _piattaforma_del_file(payload: dict) -> str | None:
    """Dominant provider platform of one catalog file, or None.

    Same rule the monitoring builder uses: a single outlier service must not
    reclassify the comune, so take the most common ``provider_platform``.
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


def mappa_eleggibili(catalog_dir: Path) -> dict[str, str]:
    """Map ``codice_istat -> platform`` for catalogued, refresh-eligible comuni.

    Only comuni whose dominant platform is in ``PIATTAFORME_REFRESH`` appear.
    """
    eleggibili: dict[str, str] = {}
    if not catalog_dir.exists():
        return eleggibili
    for percorso in catalog_dir.glob("*.json"):
        try:
            payload = json.loads(percorso.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        plat = _piattaforma_del_file(payload)
        if plat in PIATTAFORME_CATALOGO_REFRESH:
            eleggibili[percorso.stem] = plat
    return eleggibili


def seleziona(
    catalog_dir: Path,
    coda_censimento: set[str],
    gia_inizializzati: set[str],
) -> list[tuple[str, str]]:
    """Ordered ``(codice, piattaforma)`` bootstrap candidates.

    Intersection of catalog-eligible, in-queue and not-yet-initialised, sorted
    by (piattaforma, codice) so the order is stable and reproducible across
    runs — the checkpoint/resume relies on a deterministic sequence.
    """
    eleggibili = mappa_eleggibili(catalog_dir)
    candidati = [
        (codice, plat)
        for codice, plat in eleggibili.items()
        if codice in coda_censimento and codice not in gia_inizializzati
    ]
    candidati.sort(key=lambda cp: (cp[1], cp[0]))
    return candidati


def canary(
    candidati: list[tuple[str, str]], per_piattaforma: int = 2
) -> list[str]:
    """First ``per_piattaforma`` codes of each platform, round-robin.

    Round-robin (not platform-block) so a canary of 10 exercises all five
    readers early even if it is cut short: rank 0 of every platform, then rank
    1 of every platform, and so on.
    """
    per_plat: dict[str, list[str]] = defaultdict(list)
    for codice, plat in candidati:  # candidati already sorted by (plat, codice)
        if len(per_plat[plat]) < per_piattaforma:
            per_plat[plat].append(codice)
    scelti: list[str] = []
    for rango in range(per_piattaforma):
        for plat in sorted(per_plat):
            if rango < len(per_plat[plat]):
                scelti.append(per_plat[plat][rango])
    return scelti


def lotto(candidati: list[tuple[str, str]], limit: int | None) -> list[str]:
    """First ``limit`` candidate codes in selection order (all if None)."""
    codici = [codice for codice, _ in candidati]
    return codici if limit is None else codici[:limit]
