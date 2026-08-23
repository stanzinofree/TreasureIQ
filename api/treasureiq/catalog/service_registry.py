"""Registry popolato dei connettori-servizio + coordinatore di fetch (Slice 5).

Due buchi di Slice 3/4 chiusi qui:

- il ``ConnectorRegistry`` del resolver era **vuoto**: qui il factory lo popola
  con il pilota WP/AgID (le altre famiglie entreranno nello stesso factory);
- il fetch live va **guardato**: il factory non monta un ``httpx`` grezzo ma
  l'``EsecutoreServiceFetcher`` sopra un ``EsecutoreFetch`` condiviso di
  processo (rate-limit/budget/backoff/timeout centralizzati, §1.1/§1.2).

Il **coordinatore** è un'istanza unica di processo: le query live dei servizi
sono distribuite nel tempo e tra utenti, non una passata di sweep. La cache
servizi 24h (Slice 2) è la prima barriera; il coordinatore è il limite
operativo per ciò che la cache non copre. Ha budget **a finestra scorrevole**
(D-S5-9) — senza reset resterebbe bloccato per sempre a budget esaurito — ed è
la variante **serializzata per-dominio** (D-S5-10), perché la chat lo usa da più
thread via ``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import threading

from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.fetch_policy import PoliticaFetch
from treasureiq.catalog.fetch_runtime import EsecutoreFetch, EsecutoreFetchSerializzato
from treasureiq.catalog.service_connectors.esecutore_fetcher import EsecutoreServiceFetcher
from treasureiq.catalog.service_connectors.wordpress_agid import (
    WordPressAgidServiceConnector,
)

#: Tetto di richieste per dominio nella finestra e durata della finestra, per il
#: coordinatore di processo. Configurabili via env; default prudenti (poche
#: query per dominio in un'ora, la cache 24h assorbe il resto).
_ENV_BUDGET = "TREASUREIQ_SERVICE_QUERY_BUDGET"
_ENV_WINDOW_S = "TREASUREIQ_SERVICE_QUERY_BUDGET_WINDOW_S"
_DEFAULT_BUDGET = 30
_DEFAULT_WINDOW_S = 3600.0


def default_service_registry(esecutore: EsecutoreFetch) -> ConnectorRegistry:
    """Registry per-richiesta popolato col pilota WP/AgID sopra ``esecutore``.

    Il registry è per-richiesta (D-S5-1), l'``esecutore`` è condiviso di
    processo (D-S5-8): il factory lo **riceve**, non lo istanzia. I test passano
    un esecutore/fetcher stub → nessuna rete.
    """
    reg = ConnectorRegistry()
    reg.register(WordPressAgidServiceConnector(EsecutoreServiceFetcher(esecutore)))
    return reg


def _intero_env(nome: str, default: int) -> int:
    raw = os.environ.get(nome)
    if not raw:
        return default
    try:
        valore = int(raw)
    except ValueError:
        return default
    return valore if valore >= 1 else default


def _float_env(nome: str, default: float) -> float:
    raw = os.environ.get(nome)
    if not raw:
        return default
    try:
        valore = float(raw)
    except ValueError:
        return default
    return valore if valore > 0 else default


def _costruisci_coordinatore() -> EsecutoreFetchSerializzato:
    politica = PoliticaFetch(
        massimo_per_dominio=_intero_env(_ENV_BUDGET, _DEFAULT_BUDGET),
        finestra_budget_s=_float_env(_ENV_WINDOW_S, _DEFAULT_WINDOW_S),
    )
    return EsecutoreFetchSerializzato(politica)


_coordinatore: EsecutoreFetchSerializzato | None = None
_lock_coordinatore = threading.Lock()


def service_query_fetch_coordinator() -> EsecutoreFetchSerializzato:
    """L'``EsecutoreFetch`` condiviso di processo per le query live dei servizi.

    Istanza unica, costruita pigramente al primo uso e riusata: budget e
    rate-limit per dominio devono ricordare i domini toccati da tutte le
    richieste, non azzerarsi per-messaggio. La costruzione è protetta da lock
    così due thread concorrenti non creano due coordinatori distinti.
    """
    global _coordinatore
    if _coordinatore is None:
        with _lock_coordinatore:
            if _coordinatore is None:
                _coordinatore = _costruisci_coordinatore()
    return _coordinatore
