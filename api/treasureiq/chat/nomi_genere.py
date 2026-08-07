"""Lista curata nome proprio -> sesso, per una deduzione a bassa confidenza,
sempre correggibile (D-52).

Non e' un modello: e' un dizionario scritto a mano, deliberatamente piccolo,
e il lookup e' DETERMINISTICO — chiamato da `treasureiq.chat.respond` fuori
dal grammar vincolato dell'LLM, per lo stesso motivo per cui `ProfileSlots`
non porta `Decimal` ne' `pattern` (vedi `chat/intent.py`): tenere ogni cifra
o inferenza sensibile fuori dalla decodifica a grammatica di llama.cpp.

Un nome assente da queste liste resta `None`: nessun ripiego sul suffisso
italiano (-a/-o), che sbaglierebbe proprio sui nomi che lo smentiscono —
"Andrea" e "Nicola" sono nomi maschili che finiscono per "-a".
"""

from __future__ import annotations

import re
from typing import Literal

#: Piccola e scritta a mano di proposito: ogni voce e' un nome dove il
#: suffisso da solo non basterebbe (o sbaglierebbe) a deciderne il genere.
NOMI_FEMMINILI: frozenset[str] = frozenset(
    {
        "alessia",
        "maria",
        "anna",
        "giulia",
        "francesca",
        "chiara",
        "sara",
        "laura",
        "elena",
        "paola",
        "silvia",
        "valentina",
        "federica",
        "martina",
        "roberta",
        "cristina",
        "monica",
        "barbara",
        "simona",
        "alessandra",
        "giovanna",
        "carla",
        "daniela",
        "stefania",
        "elisa",
        "veronica",
        "beatrice",
        "camilla",
        "ilaria",
        "lucia",
    }
)

#: Include deliberatamente "andrea" e "nicola": nomi maschili che finiscono
#: per "-a", la coppia che dimostra perche' non esiste un ripiego sul
#: suffisso in questo modulo.
NOMI_MASCHILI: frozenset[str] = frozenset(
    {
        "marco",
        "andrea",
        "nicola",
        "giuseppe",
        "giovanni",
        "francesco",
        "alessandro",
        "luca",
        "matteo",
        "davide",
        "simone",
        "paolo",
        "roberto",
        "stefano",
        "antonio",
        "michele",
        "fabio",
        "massimo",
        "claudio",
        "riccardo",
        "daniele",
        "emanuele",
        "gabriele",
        "lorenzo",
        "filippo",
    }
)

#: «ciao sono Alessia», «mi chiamo Marco». Il nome sta sempre dopo una di
#: queste due formule, in un messaggio scritto in prima persona.
_NOME_NEL_TESTO = re.compile(
    r"\b(?:sono|mi\s+chiamo)\s+(?P<nome>[a-zàèéìòù]+)\b", re.I
)


def sesso_da_nome(messaggio: str) -> Literal["f", "m"] | None:
    """Deduce il sesso da un nome proprio dichiarato in prima persona.

    Legge solo la parola dopo "sono"/"mi chiamo", la confronta con le due
    liste curate sopra, e non inventa nulla: ne' per un nome fuori lista
    (torna `None`), ne' per un messaggio senza quella formula. Il valore
    tornato e' una deduzione a bassa confidenza — chi lo chiama deve
    mostrarlo come correggibile, mai come filtro nascosto.
    """
    if not messaggio:
        return None
    match = _NOME_NEL_TESTO.search(messaggio)
    if not match:
        return None
    nome = match.group("nome").casefold()
    if nome in NOMI_FEMMINILI:
        return "f"
    if nome in NOMI_MASCHILI:
        return "m"
    return None
