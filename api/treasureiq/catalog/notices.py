"""Canonical `notices` contract (Ramo 2).

The bandi data has three layers that must not be conflated:

* **acquisition** — ``bandi_live.BandiLiveEsito``, produced by a networked
  engine (fetch, parse, PDF, SLM/LLM). Rich, but it already carries fields the
  chat personalised (``consigliato``/``corrisponde``/``tema``).
* **canonical** — this module: ``NoticeSnapshot``/``NoticeRecord``, the v1 data
  with ZERO presentation fields. This is what a ``notices`` DataBatch carries.
* **presentation** — ``chat.respond``: ranking and theme filtering, applied on
  top of the canonical data, never folded back into it.

The pure converter ``snapshot_da_bandi_live`` reads the acquisition result and
drops the presentation-dependent fields; ``notices_batch`` projects the snapshot
into a v1 ``DataBatch``. No network, no model call, no free-text heuristic here —
this is projection, exactly like ``flotta/_projection.py`` is for offices.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from treasureiq.bandi_live import BandiLiveEsito, BandoArricchito
from treasureiq.catalog.contracts import (
    CAPABILITY_NOTICES,
    AccessMode,
    FreshnessStatus,
    Surface,
)
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataBatch,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
)

#: The coverage outcomes the acquisition engine reports, kept verbatim so the
#: canonical layer never has to re-derive coverage from the record count.
CoverageStatus = Literal[
    "coperto_con_bandi",
    "coperto_senza_bandi",
    "non_coperto",
    "comune_ignoto",
]

#: The connector identity stamped on a notices batch. The acquisition engine is
#: ``bandi_live`` regardless of platform (a generic REST/HTML ladder, not a
#: per-vendor reader), so one name is honest here.
_CONNECTOR = ConnectorRef(name="bandi_live", version="1.0.0")


class NoticeDocument(BaseModel):
    """A file linked from a notice (ciclo17). Verbatim url + label, never the
    parsed content — reading the PDF stays on the citizen's request."""

    url: str
    etichetta: str


class NoticeSource(BaseModel):
    """Provenance of a single notice, for audit: which connector read it and
    when. The link itself is the ``NoticeRecord.url``."""

    connector: str
    fetched_at: datetime


class NoticeRecord(BaseModel):
    """One notice as canonical data — zero presentation fields.

    ``deadline`` is the verbatim quote from the page and is present only when
    ``deadline_verified`` (D-07: a deadline is shown only when it can be quoted,
    never inferred). ``notice_type`` is ``None`` on the ladders that do not
    distinguish the kind (cpt/pages) — a gap, not a guess. ``documents`` empty
    means the page linked none, never that we dropped them.
    """

    notice_id: str
    title: str
    url: str
    deadline: str | None = None
    deadline_verified: bool = False
    notice_type: str | None = None
    documents: list[NoticeDocument] = []
    source: NoticeSource | None = None


class NoticeSnapshot(BaseModel):
    """The acquisition result, normalised to canonical records.

    Compatible with ``BandiLiveEsito`` (same coverage/stage vocabulary) but
    stripped of the presentation-dependent fields (``tema`` and the per-notice
    ``consigliato``/``corrisponde``). This is the seam the DataBatch projects
    from — the chat's ranking/filtering happens strictly downstream.
    """

    source_id: str
    comune_nome: str | None = None
    #: AT entrypoint URL. `BandiLiveEsito` does not expose one today, so this is
    #: `None`: the real provenance rides per-record in `NoticeRecord.url` /
    #: `NoticeSource`. Do NOT fill it from `connettore_at` — that is a connector
    #: name/id, not a URL (Codex review) — see `connector_at` below.
    source_url: str | None = None
    platform_id: str | None = None
    #: Informative name/id of the AT connector that read the source (verbatim
    #: `BandiLiveEsito.connettore_at`). NOT a URL — kept for audit, never
    #: presented as a link.
    connector_at: str | None = None
    retrieved_at: str | None = None
    coverage_status: CoverageStatus
    retrieval_stage: str | None = None
    notices: list[NoticeRecord] = []


def _record_da_bando(bando: BandoArricchito) -> NoticeRecord:
    """Convert one enriched notice to a canonical record, dropping the
    presentation fields (``consigliato``/``corrisponde``)."""
    op = bando.opportunity
    return NoticeRecord(
        notice_id=op.id,
        title=op.title,
        url=str(op.source.url),
        # D-07: the verbatim quote rides only when the engine could verify it;
        # `scadenza` is already `None` where the page gave no citable deadline.
        deadline=bando.scadenza if bando.scadenza_verificata else None,
        deadline_verified=bando.scadenza_verificata,
        notice_type=bando.tipo,
        documents=[
            NoticeDocument(url=doc.url, etichetta=doc.etichetta)
            for doc in bando.documenti
        ],
        source=NoticeSource(
            connector=op.source.connector, fetched_at=op.source.fetched_at
        ),
    )


def snapshot_da_bandi_live(esito: BandiLiveEsito) -> NoticeSnapshot:
    """Project the acquisition result into the canonical snapshot (pure).

    Drops the presentation-dependent fields: ``esito.tema`` and each notice's
    ``consigliato``/``corrisponde`` never reach the canonical data — they are
    computed downstream, per conversation, in the presentation layer.
    """
    return NoticeSnapshot(
        source_id=esito.codice_istat,
        comune_nome=esito.comune_nome,
        # source_url stays None: connettore_at is a connector name, not a URL.
        source_url=None,
        platform_id=esito.piattaforma_at,
        connector_at=esito.connettore_at,
        retrieved_at=esito.verificato_il,
        coverage_status=esito.esito,
        retrieval_stage=esito.gradino,
        notices=[_record_da_bando(b) for b in esito.bandi],
    )


def _access_mode(coverage: CoverageStatus) -> AccessMode:
    """MEDIATED when the AT source was read (with or without notices),
    UNAVAILABLE when the comune could not be read or recognised.

    The distinction matters: ``coperto_senza_bandi`` is a source we read and
    found empty — not a coverage gap. Collapsing it into UNAVAILABLE would make
    "no notice published" look like "we cannot read this comune" (Codex review).
    """
    if coverage in ("coperto_con_bandi", "coperto_senza_bandi"):
        return AccessMode.MEDIATED
    return AccessMode.UNAVAILABLE


def _freshness(measured_at: str | None, max_age_seconds: int) -> Freshness:
    """Datetime freshness from the moment the engine read the source."""
    if measured_at is None:
        return Freshness(status=FreshnessStatus.UNKNOWN)
    try:
        retrieved_at = datetime.fromisoformat(measured_at)
    except (TypeError, ValueError):
        return Freshness(status=FreshnessStatus.INVALID)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    age = max(0, int((datetime.now(timezone.utc) - retrieved_at).total_seconds()))
    status = FreshnessStatus.FRESH if age <= max_age_seconds else FreshnessStatus.STALE
    return Freshness(status=status, retrieved_at=retrieved_at, source_age_seconds=age)


def _status(mode: AccessMode, records: list[dict], fresh: Freshness) -> DataStatus:
    """Deterministic status. UNAVAILABLE → NOT_SUPPORTED; a read-but-empty
    source → EMPTY (never NOT_SUPPORTED); otherwise FULFILLED, downgraded to
    STALE when the read is past its freshness policy."""
    if mode is AccessMode.UNAVAILABLE:
        return DataStatus.NOT_SUPPORTED
    if fresh.status in (FreshnessStatus.STALE, FreshnessStatus.INVALID):
        return DataStatus.STALE
    return DataStatus.FULFILLED if records else DataStatus.EMPTY


def notices_batch(snapshot: NoticeSnapshot, request: DataRequest) -> DataBatch:
    """Project a canonical snapshot into a v1 ``notices`` DataBatch (pure).

    The record shape is the ``NoticeRecord`` dump: presentation fields are
    already absent by construction. Coverage drives access_mode/status per the
    Ramo 2 contract (``coperto_senza_bandi`` = MEDIATED + EMPTY).
    """
    if request.surface is not Surface.TRANSPARENCY:
        raise ValueError(
            f"notices is a TRANSPARENCY capability, got surface {request.surface!r}"
        )
    if request.capability != CAPABILITY_NOTICES:
        raise ValueError(
            f"notices_batch only serves {CAPABILITY_NOTICES!r}, "
            f"got capability {request.capability!r}"
        )
    if request.source_id != snapshot.source_id:
        raise ValueError(
            f"source_id mismatch: request {request.source_id!r} "
            f"vs snapshot {snapshot.source_id!r}"
        )
    records = [notice.model_dump(mode="json") for notice in snapshot.notices]
    mode = _access_mode(snapshot.coverage_status)
    fresh = _freshness(snapshot.retrieved_at, request.freshness.max_age_seconds)
    evidence = tuple(
        EvidenceRef(evidence_id=str(record["url"]), field="url")
        for record in records
        if record.get("url")
    )
    return DataBatch(
        request_id=request.request_id,
        status=_status(mode, records, fresh),
        access_mode=mode,
        source_id=request.source_id,
        surface=request.surface,
        capability=request.capability,
        records=tuple(records),
        evidence=evidence,
        freshness=fresh,
        connector=_CONNECTOR,
    )
