"""Pure projection from a v0 ``EsitoConnettore`` into v1 record dicts.

Shared by the whole fleet on purpose: it reads the ``EsitoConnettore`` contract,
not a platform.  Municipium, ComWeb and PeopleWeb all populate the same shape
(a flat ``uffici`` list plus an optional ``amministrazione_trasparente``), so the
record shaping is identical — and identical to what the WordPress adapter emits,
which is exactly the v0 office rail the citizen already sees.

Independence between connectors does NOT live here: it lives in the per-(platform
× surface) connector units, each with its own name, version and fingerprint stamp.
This module is only the stable contract they all agree on, so a platform can bump
its version without any change reaching this file.

No network here — the ``esito`` was already acquired by ``leggi_connettore``; this
is projection, never a re-fetch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from treasureiq.catalog.contracts import AccessMode, FreshnessStatus, Surface
from treasureiq.catalog.data_contracts import DataStatus, EvidenceRef, Freshness
from treasureiq.connettore import EsitoConnettore


def records(
    surface: Surface,
    capability: str,
    esito: EsitoConnettore | None,
) -> list[dict[str, Any]]:
    """Project the acquired result into the record dicts for one capability."""
    uffici = esito.uffici if esito else []
    if surface is Surface.ORDINARY_DATA and capability == "offices":
        # Dump completo: porta anche i campi additivi (indirizzo, responsabile)
        # senza doverli enumerare — la scheda-ufficio intera è il record.
        return [office.model_dump(mode="json") for office in uffici]
    if surface is Surface.ORDINARY_DATA and capability == "contacts":
        # Recapiti + `indirizzo` (canale fisico, "dove vado di persona").
        # Gate invariato sui recapiti telematici: l'indirizzo è supplementare,
        # non basta da solo a far comparire un ufficio fra i "contatti".
        # `responsabile` resta fuori dai contatti: l'accountability viaggia nel
        # dump `offices` (la scheda intera), non in una capability separata.
        return [
            {
                "nome": office.nome,
                "url": office.url,
                "telefoni": office.telefoni,
                "email": office.email,
                "pec": office.pec,
                "indirizzo": office.indirizzo,
            }
            for office in uffici
            if office.telefoni or office.email or office.pec
        ]
    if surface is Surface.TRANSPARENCY and capability == "transparency":
        at = esito.amministrazione_trasparente if esito else None
        return [at.model_dump(mode="json")] if at else []
    return []


def access_mode(
    surface: Surface,
    capability: str,
    esito: EsitoConnettore | None,
) -> AccessMode:
    """MEDIATED when the connector surfaced records, else UNAVAILABLE.

    These platforms expose structured data only through a dedicated HTML
    connector, never a typed-REST field, so DIRECT is unreachable.  An empty
    result maps to UNAVAILABLE (not EMPTY) because the v0 office rail treats an
    empty ``uffici`` as "not served" — collapsing them keeps the v1 verdict
    identical to v0's.
    """
    return AccessMode.MEDIATED if records(surface, capability, esito) else AccessMode.UNAVAILABLE


def evidence(record_dicts: list[dict[str, Any]]) -> tuple[EvidenceRef, ...]:
    """One evidence pointer per record that carries a source URL."""
    return tuple(
        EvidenceRef(evidence_id=str(record["url"]), field="url")
        for record in record_dicts
        if record.get("url")
    )


def freshness(measured_at: str, max_age_seconds: int) -> Freshness:
    """Datetime freshness from the moment the v0 connector read the source."""
    try:
        retrieved_at = datetime.fromisoformat(measured_at)
    except (TypeError, ValueError):
        return Freshness(status=FreshnessStatus.INVALID)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    age = max(0, int((datetime.now(timezone.utc) - retrieved_at).total_seconds()))
    status = FreshnessStatus.FRESH if age <= max_age_seconds else FreshnessStatus.STALE
    return Freshness(status=status, retrieved_at=retrieved_at, source_age_seconds=age)


def status(
    mode: AccessMode,
    record_dicts: list[dict[str, Any]],
    fresh: Freshness,
) -> DataStatus:
    """Deterministic status from access mode, record count and freshness."""
    if mode is AccessMode.UNAVAILABLE:
        return DataStatus.NOT_SUPPORTED
    if fresh.status in (FreshnessStatus.STALE, FreshnessStatus.INVALID):
        return DataStatus.STALE
    return DataStatus.FULFILLED if record_dicts else DataStatus.EMPTY
