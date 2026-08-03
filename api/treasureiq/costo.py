"""What it costs TreasureIQ to keep one comune readable.

Deliberately separate from `readiness.py`. The pagella scores how openly a
comune publishes — a statement about them. This scores what we have to spend
to read what they published — a statement about us. Merging the two would let
our hardware, our network and the size of their PDFs leak into a judgement of
their administration, which D-26 rule 3 rules out.

Three costs, and the third is the one usually forgotten:

  * **discovery** — finding out where the data lives at all, and by which
    route. Paid once per comune, by whoever asks about it first.
  * **retrieval** — per record: structured fields cost nothing to read, prose
    in a PDF costs an extraction attempt that may recover nothing.
  * **re-discovery** — portals move. A discovery older than
    `SOGLIA_RISCOPERTA` has to be paid again, and until it is, everything
    downstream rests on an assumption nobody has checked recently.

The index is built from *counted facts*, never from wall-clock time. Time
measures our machine and their file sizes as much as their openness: a comune
publishing heavy PDFs would score worse than one publishing light ones at
identical openness, and two runs on different hardware would disagree. Seconds
are still reported — they are the most legible evidence a reader has — but
they do not enter the score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from treasureiq.integration import AccessMode, Ente
from treasureiq.schema import Confidence, Opportunity, RecoveryLevel

#: How long a discovery stays good. Municipal portals are redesigned, migrated
#: and re-pathed without notice, and a route confirmed a week ago is a
#: reasonable bet while one confirmed a month ago is a guess. Short enough to
#: catch a migration before it silently empties a catalogue, long enough that
#: re-probing is not itself a cost worth avoiding.
SOGLIA_RISCOPERTA = timedelta(days=7)

#: Relative effort of each rung of D-21, in units of "one ingestion through a
#: documented interface". These are judgement calls, written as numbers so they
#: can be argued with instead of hiding in prose.
#:
#: The jumps are not linear because the work is not. Reading a typed field is
#: the unit. Prose inside an API costs an extraction attempt that can fail
#: silently. An attachment adds fetching and parsing a PDF before the
#: extraction can even start. A bespoke connector has to be written for one
#: portal and breaks whenever that portal is redesigned, which is why it costs
#: several times a parser rather than a little more. Nothing published and
#: open-web scraping cost the most and, separately, yield the weakest evidence
#: — the price is high and what you buy is worth less.
COSTO_GRADINO: dict[AccessMode, int] = {
    AccessMode.M1_CAMPO_TIPIZZATO: 1,
    AccessMode.M2_PROSA_API: 3,
    AccessMode.M3_ALLEGATO: 5,
    AccessMode.M4_CONNETTORE: 8,
    AccessMode.M5_NESSUNO: 13,
    AccessMode.M6_WEB_APERTO: 13,
}


@dataclass
class VoceCosto:
    """One component, with the fact it was computed from."""

    chiave: str
    etichetta: str
    valore: float
    evidenza: str


@dataclass
class CostoComune:
    ente: str
    codice_istat: str
    modo: AccessMode
    scoperta_il: date
    eta_scoperta_giorni: int
    scoperta_scaduta: bool
    record_totali: int
    record_strutturati: int
    record_recuperati_da_prosa: int
    record_non_recuperati: int
    secondi_recupero: float | None
    voci: list[VoceCosto] = field(default_factory=list)
    #: Total relative effort. Not a grade out of a hundred: a count of units,
    #: where one unit is a single ingestion through a documented interface.
    costo_totale: float = 0.0

    @property
    def costo_per_record(self) -> float | None:
        if not self.record_totali:
            return None
        return round(self.costo_totale / self.record_totali, 2)


def _classifica(record: Opportunity) -> str:
    """Which of the three states one record is in.

    `requirements_recovered` is `None` when extraction never ran and a real 0
    when it ran and recovered nothing — the distinction the whole recovery
    instrumentation exists to preserve, so it is honoured here rather than
    collapsed with a falsy check.
    """
    if record.confidence is Confidence.DECLARED and not record.requirements.is_empty:
        return "strutturato"
    if record.recovery_level is None:
        return "non_recuperato"
    if record.requirements_recovered:
        return "recuperato"
    return "non_recuperato"


def costo_comune(*, ente: Ente, records: list[Opportunity], oggi: date | None = None) -> CostoComune:
    """Compute what this comune costs us, and show the working."""
    oggi = oggi or date.today()
    eta = (oggi - ente.probe.dated).days
    scaduta = eta > SOGLIA_RISCOPERTA.days

    stati = [_classifica(r) for r in records]
    strutturati = stati.count("strutturato")
    recuperati = stati.count("recuperato")
    non_recuperati = stati.count("non_recuperato")

    secondi = [r.extraction_seconds for r in records if r.extraction_seconds is not None]
    totale_secondi = round(sum(secondi), 1) if secondi else None

    base = float(COSTO_GRADINO.get(ente.access_mode, 13))
    voci = [
        VoceCosto(
            chiave="scoperta",
            etichetta="Scoperta della via d'accesso",
            valore=base,
            evidenza=(
                f"Accesso {ente.access_mode.value}, accertato il "
                f"{ente.probe.dated.isoformat()} — {ente.probe.method}."
            ),
        )
    ]

    # Records whose criteria had to be pulled out of prose are the recurring
    # cost: every republication of the same page pays the extraction again,
    # while a structured field is read once and stays read.
    if recuperati or non_recuperati:
        voci.append(
            VoceCosto(
                chiave="estrazione",
                etichetta="Criteri da estrarre dalla prosa",
                valore=round((recuperati + non_recuperati) * 0.5, 1),
                evidenza=(
                    f"{recuperati + non_recuperati} record su {len(records)} non "
                    f"pubblicano requisiti strutturati; di questi {recuperati} hanno "
                    f"restituito qualcosa e {non_recuperati} nulla."
                ),
            )
        )

    if scaduta:
        voci.append(
            VoceCosto(
                chiave="riscoperta",
                etichetta="Riscoperta necessaria",
                valore=base,
                evidenza=(
                    f"L'ultima verifica della via d'accesso ha {eta} giorni, oltre la "
                    f"soglia di {SOGLIA_RISCOPERTA.days}. Finché non viene rifatta, "
                    "tutto quello che leggiamo da qui poggia su un percorso che "
                    "nessuno ha ricontrollato."
                ),
            )
        )

    return CostoComune(
        ente=ente.ente,
        codice_istat=ente.codice_istat,
        modo=ente.access_mode,
        scoperta_il=ente.probe.dated,
        eta_scoperta_giorni=eta,
        scoperta_scaduta=scaduta,
        record_totali=len(records),
        record_strutturati=strutturati,
        record_recuperati_da_prosa=recuperati,
        record_non_recuperati=non_recuperati,
        secondi_recupero=totale_secondi,
        voci=voci,
        costo_totale=round(sum(v.valore for v in voci), 1),
    )
