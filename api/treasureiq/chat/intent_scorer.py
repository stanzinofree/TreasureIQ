"""Scorer intent livello A — classificatore deterministico topic/kind.

Riferimento eseguibile del contratto descritto in `tiq_intent/taxonomy.toml`.
E' l'ORACOLO: il crate Rust `tiq_intent` (PyO3) deve produrre esattamente
questo output sugli stessi input (`tiq_intent/cases.json`). Finche' il crate
non e' compilato, questo modulo E' anche il backend usato a runtime
(`TREASUREIQ_INTENT_BACKEND=python`), cosi' il valore livello A — determinismo,
testabilita', recall estesa — e' gia' disponibile senza il modello.

Cosa NON fa (di proposito): non tocca `comune_hint`, gli slot anagrafici, il
`beneficiary_role`. Quelli restano dove sono — la cintura deterministica di
`extract_intent` (R-8, R-9) gira INVARIATA sopra questo output. Qui si
sostituisce solo la scatola fuzzy che oggi chiede il topic/kind al modello.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: La taxonomy vive accanto al crate: fonte unica per Python e Rust.
_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "tiq_intent" / "taxonomy.toml"

#: Sotto questa confidence il topic e' troppo incerto: si ripiega a
#: "sconosciuto" (fallimento sicuro, la chat chiede la categoria). Un hit
#: unico ha confidence 1.0; due topic vicini scendono verso 0.5.
_SOGLIA_CONFIDENCE = 0.60


@dataclass(frozen=True)
class ScoreResult:
    """Esito dello scorer. `topic`/`kind` sono i *valori* stringa degli enum
    di `treasureiq.chat.intent`, non gli enum: questo modulo non importa da
    intent.py per restare un componente foglia (e portabile 1:1 in Rust)."""

    topic: str
    kind: str
    confidence: float


@dataclass(frozen=True)
class _Taxonomy:
    topic_keywords: dict[str, tuple[str, ...]]
    informational_by_nature: frozenset[str]
    agevolazione_markers: tuple[str, ...]
    informazione_markers: tuple[str, ...]


@lru_cache(maxsize=1)
def _carica_taxonomy() -> _Taxonomy:
    with _TAXONOMY_PATH.open("rb") as fh:
        raw = tomllib.load(fh)
    topics = {name: tuple(cfg["keywords"]) for name, cfg in raw["topic"].items()}
    kind = raw["kind"]
    return _Taxonomy(
        topic_keywords=topics,
        informational_by_nature=frozenset(raw["informational_by_nature"]),
        agevolazione_markers=tuple(kind["agevolazione_markers"]),
        informazione_markers=tuple(kind["informazione_markers"]),
    )


def _peso(keyword: str) -> int:
    """Specificita' = numero di token. La frase piu' lunga vince sul pareggio
    ("tassa rifiuti" batte "rifiuti")."""
    return keyword.rstrip("-").split().__len__() or 1


@lru_cache(maxsize=4096)
def _matcher(keyword: str) -> re.Pattern[str]:
    """Confine di PAROLA, non sottostringa nuda: "tributo" non deve matchare
    "con-tributo", "metro" non deve matchare "metropolitana" (la trappola
    substring che ha morso comuni e connettivi altrove nel progetto). Un
    trattino finale e' uno stem: confine a sinistra, aperto a destra
    ("disabil-" prende disabile / disabili / disabilita)."""
    if keyword.endswith("-"):
        return re.compile(rf"\b{re.escape(keyword[:-1])}")
    return re.compile(rf"\b{re.escape(keyword)}\b")


def _presente(keyword: str, testo: str) -> bool:
    return _matcher(keyword).search(testo) is not None


def _kind_per(topic: str, testo: str, tax: _Taxonomy) -> str:
    if topic in tax.informational_by_nature:
        return "informazione"
    ag = any(_presente(m, testo) for m in tax.agevolazione_markers)
    info = any(_presente(m, testo) for m in tax.informazione_markers)
    if ag and not info:
        return "agevolazione"
    if info and not ag:
        return "informazione"
    # pareggio o assenza: la scelta conservativa non promette un verdetto.
    return "informazione"


@lru_cache(maxsize=2048)
def score_intent(message: str) -> ScoreResult:
    """Classifica un messaggio in (topic, kind, confidence). Deterministico.

    Memoizzato come i riconoscitori di `filtri.py`: stesso testo, stesso esito.
    """
    if not message or not message.strip():
        return ScoreResult(topic="sconosciuto", kind="informazione", confidence=0.0)
    tax = _carica_taxonomy()
    testo = message.casefold()

    # peso massimo per topic
    punteggi: dict[str, int] = {}
    for topic, keywords in tax.topic_keywords.items():
        best = 0
        for kw in keywords:
            if _presente(kw, testo):
                p = _peso(kw)
                if p > best:
                    best = p
        if best:
            punteggi[topic] = best

    if not punteggi:
        return ScoreResult(topic="sconosciuto", kind="informazione", confidence=0.0)

    ordinati = sorted(punteggi.items(), key=lambda kv: kv[1], reverse=True)
    top_topic, top_score = ordinati[0]
    secondo = ordinati[1][1] if len(ordinati) > 1 else 0

    # pareggio al peso massimo fra topic diversi -> ambiguo -> sconosciuto
    if secondo == top_score:
        return ScoreResult(topic="sconosciuto", kind="informazione", confidence=0.5)

    confidence = top_score / (top_score + secondo)
    if confidence < _SOGLIA_CONFIDENCE:
        return ScoreResult(topic="sconosciuto", kind="informazione", confidence=confidence)

    return ScoreResult(
        topic=top_topic,
        kind=_kind_per(top_topic, testo, tax),
        confidence=confidence,
    )
