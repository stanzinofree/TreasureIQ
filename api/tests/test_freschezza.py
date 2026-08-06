"""Test sulla dimensione "freschezza" del Data Readiness Score.

Il difetto che questi test bloccano: la prima versione di `_score_freshness`
guardava `opens_at` (la data di pubblicazione) su *tutti* i record, quindi un
catalogo di servizi permanenti — Albano Laziale non ha un solo record con
scadenza — veniva giudicato "stantio" per non avere date, anche se un
servizio permanente (scuolabus, mensa) non ha nulla da scadere. Il criterio
corretto guarda `deadline`: solo le misure a scadenza entrano nel rapporto, i
servizi permanenti ne restano fuori, e un bando scaduto continua a pesare.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import json

from treasureiq.readiness import WEIGHTS, _score_freshness
from treasureiq.schema import Opportunity

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = REPO_ROOT / "data" / "seed" / "albano_058003.json"


def _carica_seed() -> list[Opportunity]:
    raw = json.loads(SEED_PATH.read_text("utf-8"))
    return [Opportunity.model_validate(item) for item in raw]


def test_catalogo_permanente_non_e_penalizzato():
    """I 42 record di Albano non hanno un solo `deadline`: sono servizi
    permanenti, non bandi. Il vecchio criterio (basato su `opens_at`) li
    avrebbe giudicati stantii; quello nuovo deve riconoscere che qui non
    c'è nulla che possa scadere e assegnare il peso pieno."""
    record = _carica_seed()
    assert all(r.deadline is None for r in record), "fixture attesa: nessuna scadenza in Albano"

    punteggio = _score_freshness(record)

    assert punteggio.earned == WEIGHTS["freshness"]
    assert punteggio.remedy == ""
    assert "permanenti" in punteggio.evidence


def test_bando_scaduto_nel_2024_e_penalizzato():
    """Un bando con scadenza nel 2024 è scaduto ben oltre l'orizzonte di
    freschezza (400 giorni): deve pesare come record stantio, non essere
    escluso dal rapporto come farebbe un servizio permanente."""
    seed = _carica_seed()
    bando_scaduto = seed[0].model_copy(update={"deadline": date(2024, 1, 1)})

    punteggio = _score_freshness([bando_scaduto], today=date(2026, 8, 6))

    assert punteggio.earned == 0.0
    assert punteggio.remedy != ""
    assert "0/1" in punteggio.evidence


def test_servizio_permanente_non_diluisce_il_bando_scaduto():
    """Un servizio permanente mescolato a un bando scaduto non deve finire
    nel denominatore: solo le misure a scadenza contano nel rapporto, altrimenti
    un catalogo con un solo bando scaduto e novantanove servizi permanenti
    risulterebbe quasi fresco per errore."""
    seed = _carica_seed()
    servizio_permanente = seed[0]
    bando_scaduto = seed[1].model_copy(update={"deadline": date(2024, 1, 1)})

    punteggio = _score_freshness([servizio_permanente, bando_scaduto], today=date(2026, 8, 6))

    assert punteggio.earned == 0.0
    assert "0/1" in punteggio.evidence


def test_bando_con_scadenza_futura_non_e_penalizzato():
    """Una scadenza ancora da venire (o comunque dentro l'orizzonte) non è
    un catalogo abbandonato: deve pesare come fresca."""
    seed = _carica_seed()
    bando_valido = seed[0].model_copy(update={"deadline": date(2027, 1, 1)})

    punteggio = _score_freshness([bando_valido], today=date(2026, 8, 6))

    assert punteggio.earned == WEIGHTS["freshness"]
    assert punteggio.remedy == ""
