"""Pianificatore dry-run dello sweep di catalogo servizi (Step 1).

Censisce, SENZA rete e SENZA scritture, quali comuni compongono il lotto
servizi e quante ``ServiceKey`` andrebbero risolte se lo sweep girasse davvero.
Non risolve nulla, non tocca la cache: legge solo lo stato del catalogo su disco
attraverso i tre seam iniettati dal chiamante.

Puro per costruzione: nessun import di rete, nessun executor.  Il wiring reale
(``sweep_worker``) fornisce i seam concreti — mappa da cache, predicato di
supporto del registry, stato della cache servizi — mentre i test iniettano
fake.  L'esecuzione reale (scrittura ``ServiceReference``) è lo Step 2 e non
vive qui.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Sequence

from treasureiq.catalog.service_contracts import ServiceKey

#: source_id → platform_id catalogato (``None`` se manca/scaduta la mappa).
PlatformDi = Callable[[str], str | None]
#: platform_id → risolvibile da un connettore servizi registrato.
Supportata = Callable[[str], bool]
#: (source_id, chiave) → cache servizi fresca già presente su disco.
InCache = Callable[[str, ServiceKey], bool]

#: Esiti possibili per un comune nel censimento dry-run.
ESITO_NO_MAPPA = "no_mappa"
ESITO_NON_SUPPORTATA = "platform_non_supportata"
ESITO_PIANIFICATO = "pianificato"


@dataclass(frozen=True)
class RigaComune:
    """Verdetto dry-run per un singolo comune."""

    source_id: str
    platform_id: str | None
    esito: str
    chiavi_in_cache: tuple[ServiceKey, ...] = ()
    chiavi_da_risolvere: tuple[ServiceKey, ...] = ()


@dataclass(frozen=True)
class AggregatoPiattaforma:
    """Riepilogo per una piattaforma supportata."""

    platform_id: str
    comuni: int
    chiavi_in_cache: int
    chiavi_da_risolvere: int

    @property
    def risoluzioni_da_tentare(self) -> int:
        """Risoluzioni che lo sweep reale tenterebbe (una per chiave miss).

        Non è il numero di richieste HTTP: un connettore può costare più di un
        fetch per chiave.  È il conteggio onesto delle chiavi da risolvere.
        """
        return self.chiavi_da_risolvere


@dataclass(frozen=True)
class ServiceSweepDryReport:
    """Censimento completo del lotto servizi, senza rete né scritture."""

    righe: tuple[RigaComune, ...]
    per_piattaforma: tuple[AggregatoPiattaforma, ...]
    comuni_totali: int
    comuni_pianificati: int
    comuni_senza_mappa: int
    comuni_non_supportati: int
    chiavi_in_cache: int
    chiavi_da_risolvere: int

    @property
    def risoluzioni_da_tentare(self) -> int:
        return self.chiavi_da_risolvere


def pianifica_dry_run(
    comuni: Sequence[str],
    *,
    platform_di: PlatformDi,
    supportata: Supportata,
    in_cache: InCache,
) -> ServiceSweepDryReport:
    """Classifica ogni comune e aggrega, senza rete né scritture.

    Per ogni comune: nessuna mappa → ``no_mappa``; piattaforma non risolvibile
    → ``platform_non_supportata``; altrimenti ``pianificato`` con le 5
    ``ServiceKey`` ripartite fra già-in-cache e da-risolvere.
    """
    righe: list[RigaComune] = []
    for source_id in comuni:
        platform_id = platform_di(source_id)
        if platform_id is None:
            righe.append(RigaComune(source_id, None, ESITO_NO_MAPPA))
            continue
        if not supportata(platform_id):
            righe.append(RigaComune(source_id, platform_id, ESITO_NON_SUPPORTATA))
            continue
        in_c: list[ServiceKey] = []
        da_ris: list[ServiceKey] = []
        for chiave in ServiceKey:
            (in_c if in_cache(source_id, chiave) else da_ris).append(chiave)
        righe.append(
            RigaComune(
                source_id,
                platform_id,
                ESITO_PIANIFICATO,
                tuple(in_c),
                tuple(da_ris),
            )
        )

    return _aggrega(tuple(righe))


def _aggrega(righe: tuple[RigaComune, ...]) -> ServiceSweepDryReport:
    hit_per_pf: dict[str, int] = defaultdict(int)
    miss_per_pf: dict[str, int] = defaultdict(int)
    comuni_per_pf: dict[str, int] = defaultdict(int)
    senza_mappa = non_supportati = pianificati = 0

    for riga in righe:
        if riga.esito == ESITO_NO_MAPPA:
            senza_mappa += 1
        elif riga.esito == ESITO_NON_SUPPORTATA:
            non_supportati += 1
        elif riga.esito == ESITO_PIANIFICATO:
            pianificati += 1
            pf = riga.platform_id or ""
            comuni_per_pf[pf] += 1
            hit_per_pf[pf] += len(riga.chiavi_in_cache)
            miss_per_pf[pf] += len(riga.chiavi_da_risolvere)

    per_piattaforma = tuple(
        AggregatoPiattaforma(
            platform_id=pf,
            comuni=comuni_per_pf[pf],
            chiavi_in_cache=hit_per_pf[pf],
            chiavi_da_risolvere=miss_per_pf[pf],
        )
        for pf in sorted(comuni_per_pf)
    )

    return ServiceSweepDryReport(
        righe=righe,
        per_piattaforma=per_piattaforma,
        comuni_totali=len(righe),
        comuni_pianificati=pianificati,
        comuni_senza_mappa=senza_mappa,
        comuni_non_supportati=non_supportati,
        chiavi_in_cache=sum(hit_per_pf.values()),
        chiavi_da_risolvere=sum(miss_per_pf.values()),
    )
