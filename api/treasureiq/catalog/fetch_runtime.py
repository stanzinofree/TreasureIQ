"""Aggancio runtime della `PoliticaFetch` a `fetch_guardato` (Fase 2D wiring).

La `PoliticaFetch` è **pura**: decide su un `now` iniettato, non dorme e non
scarica. Qui vive la parte sporca — leggere l'orologio, dormire l'attesa
imposta, chiamare il fetch guardato, registrare il consumo del budget/rate-limit.
Orologio e sleep sono iniettabili, così il test verifica *quanto* si è aspettato
e *cosa* è stato chiamato senza dormire davvero.

Sequenza per ogni fetch (l'ordine chiesto dalla review):
1. `decidi()` sullo stato del dominio + i fallimenti consecutivi persistiti;
2. se non consentito (budget esaurito) → non si scarica, si ritorna il rifiuto;
3. si dorme l'attesa (max fra rate-limit e backoff);
4. si esegue il fetch guardato;
5. si `registra()` il consumo per il prossimo giro.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from treasureiq.catalog.fetch_policy import PoliticaFetch
from treasureiq.ingest.host_guard import fetch_guardato


@dataclass(frozen=True)
class EsitoFetch:
    """Risultato di un fetch mediato dalla politica.

    `consentito=False` significa che la politica ha rifiutato la richiesta
    (budget del dominio esaurito): l'endpoint NON è stato interrogato, quindi
    non va prodotto alcun check — è diverso da `fetched=None`, che invece è un
    endpoint interrogato ma irraggiungibile.
    """

    consentito: bool
    # La forma della tupla dipende dai kwargs del fetch: 3-tupla normale, oppure
    # 4-tupla (headers, data, url, status) con `return_non_200=True` (discovery).
    fetched: tuple | None
    motivo: str


def _ora_utc() -> datetime:
    return datetime.now(timezone.utc)


class EsecutoreFetch:
    """Media ogni fetch attraverso una `PoliticaFetch` condivisa fra endpoint.

    Una sola istanza va condivisa per l'intero lotto di sweep: budget e
    rate-limit sono *per dominio*, quindi devono ricordare i domini già toccati
    dagli altri comuni del lotto (è così che si evita di martellare un host
    SaaS comune a molti comuni).
    """

    def __init__(
        self,
        politica: PoliticaFetch,
        *,
        orologio: Callable[[], datetime] = _ora_utc,
        dormi: Callable[[float], None] = time.sleep,
    ) -> None:
        self._politica = politica
        self._orologio = orologio
        self._dormi = dormi

    def esegui(
        self, url: str, *, fallimenti_consecutivi: int = 0, **fetch_kwargs: object
    ) -> EsitoFetch:
        decisione = self._politica.decidi(
            url, self._orologio(), fallimenti_consecutivi=fallimenti_consecutivi
        )
        if not decisione.consentito:
            return EsitoFetch(consentito=False, fetched=None, motivo=decisione.motivo)
        if decisione.attesa_s > 0:
            self._dormi(decisione.attesa_s)
        fetched = fetch_guardato(url, **fetch_kwargs)  # type: ignore[arg-type]
        self._politica.registra(url, self._orologio())
        return EsitoFetch(consentito=True, fetched=fetched, motivo=decisione.motivo)
