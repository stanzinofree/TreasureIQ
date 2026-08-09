"""Rete di caratterizzazione per intent.py/respond.py (ciclo 11, B1).

Congela l'output OSSERVABILE ATTUALE delle guardie deterministiche — non
cosa VORREMMO restituissero. Ogni test qui sotto deve restare verde finche'
nessuno tocca intent.py/respond.py; il giorno in cui D-05 li riscrive, i
casi marcati `oggi_non_colto=True` nel corpus sono quelli che ci si aspetta
cambino (il commento su ciascuno dice in cosa).

Nessuna chiamata a Ollama/rete: si chiamano direttamente le funzioni
deterministiche (`slot_dal_testo`, `_disabilita_dichiarata_nel_testo`,
`_figlio_disabile_dichiarato_nel_testo`, `_sesso_dichiarato_nel_testo`,
`_comuni_candidati`) — le uniche toccate da testo libero senza passare dal
modello. `extract_intent` (che chiama `provider.aparse`) non e' invocato in
questo file: le sue guardie di post-processing sono gia' testate a parte
in `test_intent_guardie.py` con un provider finto; qui l'obiettivo e'
un'altra fetta, le funzioni-testo pure, con un corpus esplicito e
riutilizzabile da B2.
"""

from __future__ import annotations

import pytest

from tests.corpus_filtri import CORPUS, CasoTesto, casi_per_categoria
from treasureiq.chat.intent import (
    ProfileSlots,
    _disabilita_dichiarata_nel_testo,
    _figlio_disabile_dichiarato_nel_testo,
    _sesso_dichiarato_nel_testo,
    slot_dal_testo,
)
from treasureiq.chat.respond import _comuni_candidati, _profile_from_slots
from treasureiq.chat.intent import ChatIntent, Topic


# ---------------------------------------------------------------------------
# eta' / ISEE / nucleo familiare / figli minori: tutti letti da
# `slot_dal_testo`, mai dal modello (vedi il docstring della funzione).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "caso",
    [
        c
        for c in CORPUS
        if c.categoria in ("eta", "isee", "nucleo", "figli_minori")
    ],
    ids=lambda c: c.id,
)
def test_slot_dal_testo_congela_atteso_attuale(caso: CasoTesto) -> None:
    trovati = slot_dal_testo(caso.testo)
    for chiave, valore_atteso in caso.atteso.items():
        if valore_atteso is None:
            assert chiave not in trovati, (caso.id, caso.testo, trovati)
        else:
            assert trovati.get(chiave) == pytest.approx(valore_atteso), (
                caso.id,
                caso.testo,
                trovati,
            )
    if not caso.atteso:
        # Nessuna chiave attesa: il testo non deve produrre nulla di rilevante.
        assert trovati == {}, (caso.id, caso.testo, trovati)


# ---------------------------------------------------------------------------
# negazioni: lo scar vero e proprio — le guardie NON guardano la negazione.
# Congelato cosi' com'e' (imperfetto), non come vorremmo che fosse.
# ---------------------------------------------------------------------------


def test_negazione_figli_minori_non_e_gestita_oggi() -> None:
    # atteso-attuale, ciclo11 cambia in: {} (nessun figlio minore letto)
    assert slot_dal_testo("non ho figli minori") == {"figli_minori": 1}


def test_negazione_non_produce_falso_positivo_senza_qualificatore_adiacente() -> None:
    assert slot_dal_testo("mia figlia è maggiorenne") == {}


def test_negazione_disabilita_non_e_gestita_oggi() -> None:
    # atteso-attuale, ciclo11 cambia in: False
    assert _disabilita_dichiarata_nel_testo("non sono disabile") is True


def test_negazione_sesso_non_e_gestita_oggi() -> None:
    # atteso-attuale — NON fixato dall'innesto ciclo11 nonostante il
    # commento del corpus (`neg-04`) preveda "cambia in: None":
    # `_sesso_dichiarato_nel_testo` resta fuori dal perimetro di
    # `riconosci_filtri`/`FiltroChiave` per esplicita scelta del brief B3
    # (il sesso e' dedotto dal nome o dichiarato, mai un `Filtro`
    # catalogato) — divergenza documentata, non un buco dimenticato.
    assert _sesso_dichiarato_nel_testo("non sono un uomo") == "m"


# ---------------------------------------------------------------------------
# ciclo11: fixato via `riconosci_filtri` — non tramite `slot_dal_testo` /
# `_disabilita_dichiarata_nel_testo`, che restano DELIBERATAMENTE intatti
# (B1/B2 frozen) e continuano a congelare il vecchio comportamento nei test
# sopra. Il fix e' visibile solo attraverso la nuova sorgente unica.
# ---------------------------------------------------------------------------


def test_riconosci_filtri_isee_non_tronca_piu_le_migliaia() -> None:
    # ciclo11: fixato, era 936.0 (isee-03/isee-04, troncamento silenzioso)
    from treasureiq.chat.filtri import FiltroChiave, riconosci_filtri

    for testo in ("ISEE di 9360 euro", "ISEE 9360"):
        filtri = {f.chiave: f.valore for f in riconosci_filtri(testo)}
        assert filtri.get(FiltroChiave.ISEE) == pytest.approx(9360.0), testo


def test_riconosci_filtri_rispetta_la_negazione_figli_minori() -> None:
    # ciclo11: fixato, era {"figli_minori": 1} (neg-01)
    from treasureiq.chat.filtri import FiltroChiave, riconosci_filtri

    filtri = {f.chiave for f in riconosci_filtri("non ho figli minori")}
    assert FiltroChiave.FIGLI_MINORI not in filtri


def test_riconosci_filtri_rispetta_la_negazione_disabilita() -> None:
    # ciclo11: fixato, era {"disabilita": True} (neg-03)
    from treasureiq.chat.filtri import FiltroChiave, riconosci_filtri

    filtri = {f.chiave for f in riconosci_filtri("non sono disabile")}
    assert FiltroChiave.DISABILITA not in filtri


# ---------------------------------------------------------------------------
# disabilita': propria/beneficiario vs figlio (R-8/D-53).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("caso", casi_per_categoria("disabilita"), ids=lambda c: c.id)
def test_disabilita_propria_vs_figlio_congela_atteso_attuale(caso: CasoTesto) -> None:
    if "disabilita" in caso.atteso:
        assert (
            _disabilita_dichiarata_nel_testo(caso.testo) is caso.atteso["disabilita"]
        ), (caso.id, caso.testo)
    if "figlio" in caso.atteso:
        assert (
            _figlio_disabile_dichiarato_nel_testo(caso.testo) is caso.atteso["figlio"]
        ), (caso.id, caso.testo)


# ---------------------------------------------------------------------------
# sesso dichiarato esplicitamente (D-52).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("caso", casi_per_categoria("sesso"), ids=lambda c: c.id)
def test_sesso_dichiarato_congela_atteso_attuale(caso: CasoTesto) -> None:
    assert _sesso_dichiarato_nel_testo(caso.testo) == caso.atteso["sesso"], (
        caso.id,
        caso.testo,
    )


# ---------------------------------------------------------------------------
# toponimi scar: parole che sono ANCHE nomi di comune, e comuni scritti
# spezzati. `_comuni_candidati` e' la funzione con la vista completa
# (quanti candidati, non solo "uno o niente" come `_comune_nominato`).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("caso", casi_per_categoria("comune"), ids=lambda c: c.id)
def test_comuni_candidati_congela_atteso_attuale(caso: CasoTesto) -> None:
    candidati = _comuni_candidati(caso.testo)
    if "candidati" in caso.atteso:
        ottenuti = [(c.nome, c.provincia) for c in candidati]
        assert ottenuti == caso.atteso["candidati"], (caso.id, caso.testo, ottenuti)
    if caso.atteso.get("ambiguo"):
        assert len(candidati) >= 2, (caso.id, caso.testo, candidati)


# ---------------------------------------------------------------------------
# employment: ciclo11/D-05 rovescia questo test. `_profile_from_slots` non
# guarda piu' `intent.slots` (sempre vuoto dopo D-01) — legge SOLO
# `riconosci_filtri(messaggio)`, che riconosce "disoccupato"/"pensionato"
# nel testo esplicito. Deviazione oltre i soli casi marcati nel corpus
# (giustificata: e' una conseguenza strutturale della sorgente unica di
# slot, non un fix mirato) — documentata qui invece che nel corpus, perche'
# il corpus stesso (`atteso={"non_estratto_dal_testo": True}`) descrive il
# comportamento PRE-innesto e resta un artefatto storico intenzionalmente
# non toccato (B1/B2 restano frozen).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("caso", casi_per_categoria("employment"), ids=lambda c: c.id)
def test_employment_status_ora_estratto_dal_testo(caso: CasoTesto) -> None:
    # ciclo11: fixato, era None (nessun ripiego testuale) — ora
    # `riconosci_filtri` legge "disoccupato"/"pensionato" dal messaggio e
    # `_profile_from_slots` non ha piu' bisogno di uno slot dal modello.
    intent = ChatIntent(topic=Topic.SCONOSCIUTO, slots=ProfileSlots(employment_status=None))
    profilo = _profile_from_slots(intent=intent, messaggio=caso.testo)
    assert profilo.employment_status is not None, (caso.id, caso.testo)
    assert profilo.employment_status.value in caso.testo, (caso.id, caso.testo)


# ---------------------------------------------------------------------------
# Copertura del corpus: ogni categoria dichiarata nel corpus e' esercitata
# da almeno un test sopra — se qualcuno aggiunge una categoria nuova al
# corpus senza aggiungere il test, questo la intercetta.
# ---------------------------------------------------------------------------

_CATEGORIE_COPERTE = {
    "eta",
    "isee",
    "nucleo",
    "figli_minori",
    "disabilita",
    "sesso",
    "comune",
    "employment",
}


def test_ogni_categoria_del_corpus_e_coperta_da_un_test() -> None:
    categorie_corpus = {c.categoria for c in CORPUS}
    mancanti = categorie_corpus - _CATEGORIE_COPERTE
    assert not mancanti, f"categorie nel corpus senza test dedicato: {mancanti}"


def test_corpus_ha_almeno_cinquanta_casi() -> None:
    assert len(CORPUS) >= 50, len(CORPUS)


def test_corpus_ids_sono_unici() -> None:
    ids = [c.id for c in CORPUS]
    assert len(ids) == len(set(ids))
