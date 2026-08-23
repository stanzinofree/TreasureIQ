"""Traccia di freschezza: gli ultimi fetch live andati a buon fine.

Ogni volta che `host_guard.fetch_guardato` scarica DAVVERO da un sito comunale
(non da cache) registra qui l'URL e la taglia. È una prova auditabile della
tesi di TreasureIQ — i dati vengono ORA dal sito del comune, non da un DB
stantio — ed è ciò che alimenta il monitoraggio interno dei fetch live. Un
cache-hit non passa mai di qui, quindi la traccia distingue da sola
il dato fresco da quello servito da disco.

Buffer in memoria, limitato: è diagnostica volatile, non uno storico. Gli URL
sono host pubblici già visibili nella `fonte` delle risposte — nessun segreto.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque

#: Quanti eventi tenere: abbastanza per una demo/sessione, non uno storico.
_MAX_EVENTI = 200

_eventi: deque[dict] = deque(maxlen=_MAX_EVENTI)
_lock = threading.Lock()
_seq = itertools.count(1)


def registra(url: str, byte: int) -> None:
    """Annota un fetch live riuscito. Thread-safe: i fetch girano concorrenti."""
    with _lock:
        _eventi.append(
            {"id": next(_seq), "url": url, "byte": byte, "ts": time.time()}
        )


def recenti(dopo: int = 0) -> list[dict]:
    """Gli eventi con `id` maggiore di `dopo` (0 = tutti quelli in buffer).

    Il client passa l'ultimo `id` visto e riceve solo i nuovi: polling
    incrementale senza doppioni."""
    with _lock:
        return [e for e in _eventi if e["id"] > dopo]
