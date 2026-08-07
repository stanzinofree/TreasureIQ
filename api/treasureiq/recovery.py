"""D-16 recovery-cost aggregation, per comune.

The recovery ladder is instrumentation about how closed a comune's data was:
how much work stood between what the comune published and a machine-readable
requirement. `RecoveryLevel` records that per opportunity; this module rolls it
up so the web UI can chart it instead of carrying transcribed constants.

The distinction this module exists to preserve is between two very different
reasons a record carries no `recovery_level`:

    typed        — the record came from the comune's own `/servizi` API, already
                   structured. There was nothing to recover, so the cost really
                   is zero. This is the good case, and a comune that publishes
                   this way deserves to be shown as costing nothing.

    unmeasured   — the record predates the instrumentation, or came from a
                   connector that does not measure. We do not know its cost.

Collapsing the second into the first would turn "we never looked" into "it was
free", which is exactly the flattering-by-omission the readiness score exists to
avoid. They are counted separately and never summed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from treasureiq.schema import Opportunity

#: Connectors that read an already-structured municipal API. A record from one
#: of these needs no recovery by construction — the comune had already done the
#: work — so its absent `recovery_level` means zero cost, not unknown cost.
TYPED_CONNECTORS = frozenset({"wp_rest"})


@dataclass(frozen=True)
class RecordCost:
    """What one opportunity cost to make machine-readable."""

    id: str
    title: str
    recovery_level: str | None
    extraction_seconds: float | None
    pdfs_linked: int | None
    pdfs_opened: int | None
    #: Count of the skipped-URL list, not the list itself: the chart needs the
    #: size, and the URLs already live in `extraction_notes` for the curious.
    pdfs_skipped: int | None
    chars_processed: int | None
    requirements_recovered: int | None


@dataclass(frozen=True)
class ComuneRecovery:
    """Rolled-up recovery cost for one comune."""

    ente: str
    codice_istat: str
    records_total: int
    typed_records: int
    recovered_records: int
    unmeasured_records: int
    levels: dict[str, int] = field(default_factory=dict)
    seconds_total: float | None = None
    seconds_avg: float | None = None
    pdfs_linked_total: int = 0
    pdfs_opened_total: int = 0
    pdfs_skipped_total: int = 0
    requirements_recovered_total: int = 0
    records: tuple[RecordCost, ...] = ()


def _level_key(record: Opportunity) -> str | None:
    level = getattr(record, "recovery_level", None)
    if level is None:
        return None
    return level.value if hasattr(level, "value") else str(level)


def _is_typed(record: Opportunity) -> bool:
    connector = getattr(record.source, "connector", None)
    return connector in TYPED_CONNECTORS


def _to_record_cost(record: Opportunity) -> RecordCost:
    # Every instrumentation field is read with `getattr(..., None)`: older
    # committed snapshots simply do not carry them, and a missing measurement
    # must stay missing rather than collapse to a confident zero.
    return RecordCost(
        id=record.id,
        title=record.title,
        recovery_level=_level_key(record),
        extraction_seconds=getattr(record, "extraction_seconds", None),
        pdfs_linked=getattr(record, "pdfs_linked", None),
        pdfs_opened=getattr(record, "pdfs_opened", None),
        pdfs_skipped=len(getattr(record, "pdfs_skipped", None) or ()),
        chars_processed=getattr(record, "chars_processed", None),
        requirements_recovered=getattr(record, "requirements_recovered", None),
    )


def compute_comune_recovery(
    *, ente: str, codice_istat: str, records: list[Opportunity]
) -> ComuneRecovery:
    """Roll every record's recovery instrumentation up to the comune.

    `seconds_avg` averages only over records that actually carry a measurement,
    so a comune with nothing to recover reports `None` rather than a zero that
    would read as "instant" on a chart.
    """
    typed = recovered = unmeasured = 0
    levels: dict[str, int] = {}
    seconds: list[float] = []
    pdfs_linked = pdfs_opened = pdfs_skipped = requirements = 0

    for record in records:
        level = _level_key(record)
        if level is not None:
            recovered += 1
            levels[level] = levels.get(level, 0) + 1
        elif _is_typed(record):
            typed += 1
        else:
            unmeasured += 1

        value = getattr(record, "extraction_seconds", None)
        if value is not None:
            seconds.append(float(value))
        pdfs_linked += getattr(record, "pdfs_linked", None) or 0
        pdfs_opened += getattr(record, "pdfs_opened", None) or 0
        # `pdfs_skipped` is the list of URLs we chose not to open, not a count.
        pdfs_skipped += len(getattr(record, "pdfs_skipped", None) or ())
        requirements += getattr(record, "requirements_recovered", None) or 0

    return ComuneRecovery(
        ente=ente,
        codice_istat=codice_istat,
        records_total=len(records),
        typed_records=typed,
        recovered_records=recovered,
        unmeasured_records=unmeasured,
        levels=levels,
        seconds_total=sum(seconds) if seconds else None,
        seconds_avg=(sum(seconds) / len(seconds)) if seconds else None,
        pdfs_linked_total=pdfs_linked,
        pdfs_opened_total=pdfs_opened,
        pdfs_skipped_total=pdfs_skipped,
        requirements_recovered_total=requirements,
        # Sorted by cost so the chart's ordering is the API's, not the client's.
        records=tuple(
            sorted(
                (_to_record_cost(r) for r in records if _level_key(r) is not None),
                key=lambda r: r.extraction_seconds or 0.0,
                reverse=True,
            )
        ),
    )
