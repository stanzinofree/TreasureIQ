"""Classificatore puro titolo → intento-azione per la disambiguazione multi-servizio.

Quando una ServiceKey risolve a ≥2 servizi (es. IMIS/OpenPA-Trentino: calcolatore,
agevolazione, comunicazione, dichiarazione, versamento/rimborso, modulistica), il
gate exactly-one rifiuta e il connettore emette ``DataStatus.DISAMBIGUATION`` con
tutte le ServiceReference. Questa funzione è la **presentazione**: raggruppa quelle
reference per intento di azione, in modo deterministico e senza rete, così la UI
può mostrare «cosa vuoi fare» invece di una lista piatta.

Regole:
- classificazione **pura** dal solo titolo (nessun fetch, nessun modello);
- ordine dei bucket **fisso** (quello di ``IntentoAzione``), non per frequenza;
- fallback **esplicito** ``ALTRO_INFORMAZIONI``: un titolo che non è un'azione
  (guida, tabella valori) NON viene scartato né forzato in un bucket sbagliato;
- il raggruppamento è presentazione, non identità: due reference nello stesso
  bucket restano due ServiceReference distinte con service_id distinti.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Iterable

from treasureiq.catalog.service_contracts import ServiceReference


class IntentoAzione(str, Enum):
    """Intento-azione del cittadino. L'ordine di dichiarazione è l'ordine di
    presentazione E l'ordine di priorità del match (il primo che matcha vince)."""

    CALCOLATORE = "calcolatore"
    AGEVOLAZIONE = "agevolazione"
    COMUNICAZIONE = "comunicazione"
    DICHIARAZIONE_ISTANZA = "dichiarazione_istanza"
    VERSAMENTO_RIMBORSO = "versamento_rimborso"
    MODULISTICA = "modulistica"
    #: Fallback esplicito, non un errore: guide, informative, tabelle valori.
    ALTRO_INFORMAZIONI = "altro_informazioni"


#: Marker per bucket, valutati NELL'ORDINE dell'enum. Derivati dal corpus reale
#: dei 481 candidati confermati sui 64 comuni OpenPA trentini ambigui.
_REGOLE: tuple[tuple[IntentoAzione, re.Pattern[str]], ...] = (
    (IntentoAzione.CALCOLATORE, re.compile(r"calcolat|calcolo|simulat", re.IGNORECASE)),
    (IntentoAzione.AGEVOLAZIONE, re.compile(r"agevolaz|esenzion|riduzion|detrazion", re.IGNORECASE)),
    (IntentoAzione.COMUNICAZIONE, re.compile(r"comunicaz|pertinen|coniug", re.IGNORECASE)),
    (IntentoAzione.DICHIARAZIONE_ISTANZA, re.compile(r"dichiaraz|domand|istanz|autocertific", re.IGNORECASE)),
    (IntentoAzione.VERSAMENTO_RIMBORSO,
     re.compile(r"versament|pagament|scaden|acconto|saldo|f24|ravvedimen|rimbors", re.IGNORECASE)),
    (IntentoAzione.MODULISTICA, re.compile(r"modul|allegat|fac.?simile", re.IGNORECASE)),
)


def classifica_intento(title: str) -> IntentoAzione:
    """Titolo → intento-azione. Fallback deterministico ``ALTRO_INFORMAZIONI``."""
    testo = title or ""
    for intento, rx in _REGOLE:
        if rx.search(testo):
            return intento
    return IntentoAzione.ALTRO_INFORMAZIONI


def raggruppa_per_intento(
    references: Iterable[ServiceReference],
) -> list[tuple[IntentoAzione, list[ServiceReference]]]:
    """Raggruppa le reference per intento, in ordine di ``IntentoAzione``.

    Ritorna solo i bucket non vuoti; l'ordine interno a ogni bucket è quello di
    ingresso (stabile). Nessuna reference viene persa: ogni titolo cade in un
    bucket, fallback incluso.
    """
    per_intento: dict[IntentoAzione, list[ServiceReference]] = {}
    for ref in references:
        per_intento.setdefault(classifica_intento(ref.title), []).append(ref)
    return [(intento, per_intento[intento]) for intento in IntentoAzione if intento in per_intento]
