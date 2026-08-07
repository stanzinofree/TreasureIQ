"""Raggruppa i ~20 `Topic` (`treasureiq.chat.intent`) in categorie civiche
per la scelta «tutte le categorie o una in particolare?» (D-55).

Il mapping è deterministico e TOTALE: ogni `Topic` tranne `SCONOSCIUTO` ha
una categoria, verificato da `tests/test_intent_guardie.py`. Nessun modello
partecipa a questa classificazione — è la stessa ragione per cui `Topic` è
un enum chiuso invece di una stringa libera (vedi `intent.py`): una categoria
sbagliata deve essere un'etichetta sbagliata, mai un fatto inventato.
"""

from __future__ import annotations

from enum import Enum

from treasureiq.chat.intent import Topic


class Categoria(str, Enum):
    """Le tre categorie che il cittadino può scegliere, più `ALTRO` per i
    `Topic` che non rientrano in nessuna delle tre — mai omessi dal mapping,
    solo non proposti come scelta esplicita in chat (D-55 propone solo
    utenze/mezzi/assegni)."""

    UTENZE = "utenze"
    MEZZI = "mezzi"
    ASSEGNI = "assegni"
    ALTRO = "altro"


#: Mapping proposto in `.kapi/spec.md` ASSUMPTIONS A5, confermato qui come
#: DISCRETION dell'arm. TOTALE sui `Topic` tranne `SCONOSCIUTO`: un `Topic`
#: dimenticato qui sparirebbe silenziosamente dalla modalità «tutte», che è
#: esattamente il tipo di buco che il contratto del silenzio (D-05/D-09) non
#: permette. Il test di totalità in `test_intent_guardie.py` lo impedisce.
CATEGORIA_PER_TOPIC: dict[Topic, Categoria] = {
    # utenze — bollette, rifiuti, tributi: il costo ricorrente della casa.
    Topic.SOSTEGNO_UTENZE: Categoria.UTENZE,
    Topic.RIFIUTI: Categoria.UTENZE,
    Topic.TRIBUTI: Categoria.UTENZE,
    # mezzi — trasporto e mobilità.
    Topic.TRASPORTO_SCOLASTICO: Categoria.MEZZI,
    Topic.TRASPORTO_PUBBLICO: Categoria.MEZZI,
    Topic.CONTRASSEGNO_DISABILI: Categoria.MEZZI,
    # assegni — contributi economici diretti.
    Topic.ASSEGNO_MATERNITA: Categoria.ASSEGNI,
    Topic.BORSA_STUDIO: Categoria.ASSEGNI,
    Topic.CONTRIBUTO_LIBRI: Categoria.ASSEGNI,
    Topic.CONTRIBUTO_AFFITTO: Categoria.ASSEGNI,
    Topic.VOUCHER_CONCILIAZIONE: Categoria.ASSEGNI,
    Topic.INCLUSIONE_SOCIALE: Categoria.ASSEGNI,
    # altro — servizi anagrafici, amministrativi, sociali non ricorrenti.
    Topic.MENSA_SCOLASTICA: Categoria.ALTRO,
    Topic.ASSISTENZA_DISABILITA: Categoria.ALTRO,
    Topic.ANAGRAFE_CARTA_IDENTITA: Categoria.ALTRO,
    Topic.ACCESSO_ATTI: Categoria.ALTRO,
    Topic.OCCUPAZIONE_SUOLO: Categoria.ALTRO,
    Topic.CAREGIVER_DOMICILIARE: Categoria.ALTRO,
    Topic.MATRIMONIO_SEPARAZIONE: Categoria.ALTRO,
    Topic.SUAP_IMPRESE: Categoria.ALTRO,
    Topic.AREA_VERDE: Categoria.ALTRO,
    Topic.VOLONTARIATO: Categoria.ALTRO,
}


def topics_di(categoria: Categoria) -> list[Topic]:
    """I `Topic` che ricadono in una categoria, nell'ordine dichiarato sopra
    — usato per filtrare i record PRIMA del ranking (D-55), mai dopo."""
    return [topic for topic, cat in CATEGORIA_PER_TOPIC.items() if cat is categoria]
