"""Sweep di *misura* della risoluzione servizi (Ramo 3 — Fase 1).

Strumento di misura, non di promozione dati. Risolve i servizi **dal vivo**
(letture di rete, rate-limited) ma **non scrive nulla**: né sulla service-cache,
né sul catalogo flat, né su ``storico.db``. Il suo unico prodotto è un report di
copertura/precisione e un checkpoint JSONL, entrambi in una cartella scratch
separata (``--out``).

Ogni riga porta due assi distinti: l'**esito** (fulfilled / ambiguita / …, la
tassonomia sotto) e la **provenienza** — da quale tier del resolver è arrivata
la risposta (``catalog`` / ``cache`` / ``live``). Servono separati: un
``fulfilled`` servito dal catalogo flat (zero rete) non è lo stesso di uno
scoperto dal vivo, e senza questa distinzione ogni misura globale sottostima
sistematicamente i cataloghi standalone (es. CSC, il cui adapter è fuori
registry ma i cui dati vivono nel catalogo flat, chiave-ISTAT).

Come misura, per ogni ``(comune, probe)``:

1. **recogniser** (``riconosci_service_key``): testo → ``ServiceKey`` | ``None``.
   ``None`` = ``chiave_non_riconosciuta`` (0 o ≥2 marker: il recogniser resta
   indeciso). Confrontato con l'attesa del golden per scovare miss/falsi-positivi
   deterministici (materiale per la Fase 2, non corretto qui).
2. **tier cache → catalogo** (``resolve_service_with_meta`` con un ConnectorRegistry
   **vuoto**): il resolver consulta cache poi catalogo flat e — registry isolato —
   NON può mai arrivare al connettore live, quindi non scrive nulla (il write-back
   del resolver è dopo il ``retrieve``, irraggiungibile). È ISTAT-keyed: non serve
   la mappa, perciò va PRIMA della sonda live, così i comuni serviti da un adapter
   standalone via catalogo non cadono in ``comune_non_risolto``. Hit → ``fulfilled``
   con provenienza ``catalog`` (o ``cache``), zero rete.
3. **comune** (solo sul miss del tier 2): mappa-connettore da cache (nessuna rete)
   + registro. Assenti → ``comune_non_risolto``.
4. **connettore live**: ``registry.resolve``; assente → ``connettore_non_disponibile``.
   - connettore con ``diagnostica`` (base condivisa): discovery + filtro + gate
     read-only, conta i confermati → ``target`` assente = ``connettore_non_disponibile``;
     0 = ``fonte_assente``; 1 = ``fulfilled``; ≥2 = ``ambiguita``;
   - connettore **senza** ``diagnostica`` (es. Magnolia, adapter su ``retrieve``):
     misura read-only via ``retrieve`` diretto (il write-back sta nel resolver, che
     qui non chiamiamo → zero scritture) → FULFILLED+1 = ``fulfilled``; NOT_SUPPORTED
     = ``connettore_non_disponibile``; resto = ``fonte_assente`` (l'ambiguità ≥2 è
     collassata dal connettore in NOT_FOUND: limite noto, annotato ``via_retrieve``).
   Tutti gli esiti del tier live portano provenienza ``live``.

Il campione è **stratificato per famiglia Base** (piattaforma in ``storico.db``)
e ogni comune porta il **tag AT** (``piattaforma_at`` presente). La superficie
**SP** non è censita per-comune (esiste solo come provenienza per-``ServiceReference``
dopo la risoluzione, che qui non persistiamo): è riportata come limite noto, non
inventata.

Uso::

    python -m treasureiq.catalog.measurement_sweep --db api/storico.db \\
        --out data/measure --per-famiglia 5 --seed 42

Riprende in automatico saltando le coppie ``(comune, probe)`` già nel checkpoint.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from treasureiq.catalog.connector_registry import ConnectorRegistry
from treasureiq.catalog.data_contracts import DataStatus
from treasureiq.catalog.fetch_policy import PoliticaFetch
from treasureiq.catalog.fetch_runtime import EsecutoreFetch
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.catalog.service_registry import default_service_registry
from treasureiq.catalog.service_resolver import (
    _CATALOG_CONNECTOR,
    resolve_service_with_meta,
)
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.mappa_connettore import (
    ProbeBudgetEsaurito,
    ProbeFallita,
    _sonda_mappa,
    comune_per_codice,
)
from treasureiq.mappa_connettore import (
    _da_cache as _mappa_da_cache,
)
from treasureiq.registro import leggi_registro
from treasureiq.storico import apri

# --- tassonomia esiti (le 6 categorie richieste + il fulfilled) --------------
ESITO_FULFILLED = "fulfilled"
ESITO_AMBIGUITA = "ambiguita"
ESITO_FONTE_ASSENTE = "fonte_assente"
ESITO_CHIAVE_NON_RICONOSCIUTA = "chiave_non_riconosciuta"
ESITO_COMUNE_NON_RISOLTO = "comune_non_risolto"
ESITO_CONNETTORE_NON_DISPONIBILE = "connettore_non_disponibile"
#: Non è una delle 6 categorie-dato: è un esito di MISURA. Endpoint non risponde
#: dopo i retry → transient/infra, NON assenza reale. Tenuto distinto perché
#: gonfiava ``fonte_assente`` (i 3 openpa ``imu_verb`` erano gli stessi comuni che
#: rispondevano su ``imu_canon``: rumore transient, non servizio mancante).
ESITO_ENDPOINT_MUTO = "endpoint_muto"

_ESITI = (
    ESITO_FULFILLED,
    ESITO_AMBIGUITA,
    ESITO_FONTE_ASSENTE,
    ESITO_CHIAVE_NON_RICONOSCIUTA,
    ESITO_COMUNE_NON_RISOLTO,
    ESITO_CONNETTORE_NON_DISPONIBILE,
    ESITO_ENDPOINT_MUTO,
)

#: Retry/backoff dello stesso endpoint quando la discovery dà 0 grezzi: serve a
#: separare l'endpoint muto (transient) dall'assenza reale. Default prudenti.
_RETRY_ENDPOINT = 2
_BACKOFF_S = 2.0

# --- provenienza (il tier del resolver che ha prodotto l'esito) ---------------
#: Secondo asse, ortogonale all'esito: `catalog`/`cache` = servito zero-rete dal
#: tier 2 del resolver; `live` = misurato dal vivo (tier 4); `""` = nessuna
#: risoluzione tentata (recogniser fermo prima dei tier).
PROV_CATALOG = "catalog"
PROV_CACHE = "cache"
PROV_LIVE = "live"
PROV_NESSUNA = ""

#: Env-gate del tier catalogo nel resolver. Lo strumento di misura DEVE contare
#: ciò che il catalogo può servire a prescindere dal rollout di produzione: lo
#: forziamo attivo attorno al probe (poi ripristinato), senza mutare lo stato
#: globale del processo.
_ENV_CATALOGO = "TREASUREIQ_SERVICE_CATALOG"

#: Registry VUOTO per il probe cache→catalogo: nessun connettore vi è registrato,
#: quindi il resolver non può raggiungere il tier live né il suo write-back →
#: garanzia strutturale di zero-scrittura del probe.
_REGISTRY_ISOLATO = ConnectorRegistry()


@contextlib.contextmanager
def _catalogo_forzato():
    """Attiva il gate del catalogo per la durata del blocco, poi ripristina.

    La misura conta sempre il catalogo (è il suo scopo), indipendentemente
    dall'env ambientale; il ripristino evita di lasciare il processo mutato.
    """
    prima = os.environ.get(_ENV_CATALOGO)
    os.environ[_ENV_CATALOGO] = "1"
    try:
        yield
    finally:
        if prima is None:
            os.environ.pop(_ENV_CATALOGO, None)
        else:
            os.environ[_ENV_CATALOGO] = prima


def _risolvi_da_catalogo(richiesta, *, registry_isolato=None):
    """Tier cache → catalogo via resolver con registry ISOLATO (zero-write).

    Ritorna il ``ResolvedService`` se cache o catalogo servono la coppia, altrimenti
    ``None`` (segnale di fall-through al tier live). ``mappa=None`` è sicuro: con un
    registry vuoto il resolver ritorna prima di toccare la mappa (usata solo dentro
    ``retrieve``, mai raggiunto).
    """
    reg = registry_isolato if registry_isolato is not None else _REGISTRY_ISOLATO
    with _catalogo_forzato():
        return resolve_service_with_meta(
            richiesta, mappa=None, registry=reg, platform_id=""
        )


@dataclass(frozen=True)
class Probe:
    """Un intento del golden set.

    ``atteso`` è la ``ServiceKey`` che il recogniser DOVREBBE marcare, oppure
    ``None`` per un probe fuori-vocabolario deliberato (deve restare non
    riconosciuto). Serve a distinguere un miss di riconoscimento (deterministico,
    materiale Fase 2) da un ``chiave_non_riconosciuta`` corretto.
    """

    probe_id: str
    raw: str
    atteso: ServiceKey | None


# Golden set: forme reali per ogni ServiceKey del vocabolario chiuso + probe
# fuori-vocabolario per misurare `chiave_non_riconosciuta` onestamente. Le forme
# "attese riconosciute" sono verificate a runtime contro il recogniser: una che
# non mappa oggi è segnalata come miss di riconoscimento, non forzata.
GOLDEN: tuple[Probe, ...] = (
    Probe("carta_canon", "carta d'identità", ServiceKey.CARTA_IDENTITA),
    Probe("carta_verb", "come rinnovo la carta d'identità", ServiceKey.CARTA_IDENTITA),
    Probe("residenza_verb", "voglio cambiare residenza", ServiceKey.CAMBIO_RESIDENZA),
    Probe("residenza_canon", "cambio di residenza", ServiceKey.CAMBIO_RESIDENZA),
    Probe("atti_canon", "accesso agli atti", ServiceKey.ACCESSO_ATTI),
    Probe("atti_var", "richiesta di accesso agli atti", ServiceKey.ACCESSO_ATTI),
    Probe("stato_civile", "stato civile", ServiceKey.STATO_CIVILE),
    Probe("imu_verb", "devo pagare l'IMU", ServiceKey.TRIBUTI_IMU),
    Probe("imu_canon", "imu", ServiceKey.TRIBUTI_IMU),
    Probe("tari_canon", "tari", ServiceKey.TRIBUTI_TARI),
    # Fuori-vocabolario deliberati: `atteso=None`, DEVONO restare non riconosciuti.
    Probe("unk_tributi", "tributi", None),  # ombrello droppato (split IMU/TARI)
    Probe("unk_contributi", "contributi", None),  # falso-amico substring di "tributi"
    Probe("unk_bonus", "bonus bebè", None),  # fuori dominio servizi
    Probe("unk_tennis", "prenotare un campo da tennis", None),  # fuori dominio
)


@dataclass(frozen=True)
class ComuneCampione:
    """Un comune del campione, con famiglia Base e tag di superficie."""

    codice_istat: str
    base_famiglia: str
    at_presente: bool


@dataclass(frozen=True)
class Misura:
    """Esito di misura di una singola coppia ``(comune, probe)``.

    Righe di questa forma sono ciò che finisce nel checkpoint JSONL e alimenta
    l'aggregato del report.
    """

    codice_istat: str
    base_famiglia: str
    at_presente: bool
    probe_id: str
    raw: str
    atteso: str | None
    riconosciuto: str | None
    recognizer_ok: bool
    esito: str
    grezzi: int
    filtrati: int
    confermati: int
    note: str = ""
    #: Tier del resolver che ha prodotto l'esito (catalog/cache/live) o "" quando
    #: nessun tier è stato interrogato (recogniser fermo). Asse ortogonale all'esito.
    provenienza: str = ""

    def chiave(self) -> tuple[str, str]:
        """Identità per il resume: una coppia comune×probe è misurata una volta."""
        return (self.codice_istat, self.probe_id)

    def to_json(self) -> dict:
        return {
            "codice_istat": self.codice_istat,
            "base_famiglia": self.base_famiglia,
            "at_presente": self.at_presente,
            "probe_id": self.probe_id,
            "raw": self.raw,
            "atteso": self.atteso,
            "riconosciuto": self.riconosciuto,
            "recognizer_ok": self.recognizer_ok,
            "esito": self.esito,
            "grezzi": self.grezzi,
            "filtrati": self.filtrati,
            "confermati": self.confermati,
            "note": self.note,
            "provenienza": self.provenienza,
        }


# --- campionamento ------------------------------------------------------------
def _snapshot_corrente(db: Path) -> list[tuple[str, str, bool]]:
    """Righe ``(codice_istat, piattaforma, at_presente)`` dell'ultimo snapshot
    per ciascun comune in ``portale_snapshot`` (chiave temporale ``rilevato_il``).
    """
    if not db.exists():
        raise SystemExit(f"storico.db assente ({db}): esegui prima lo scan nazionale.")
    with apri(db) as conn:
        righe = conn.execute(
            """
            SELECT ps.codice_istat AS codice_istat,
                   ps.piattaforma AS piattaforma,
                   ps.piattaforma_at AS piattaforma_at
            FROM portale_snapshot ps
            JOIN (
                SELECT codice_istat, MAX(rilevato_il) AS m
                FROM portale_snapshot GROUP BY codice_istat
            ) latest
              ON ps.codice_istat = latest.codice_istat
             AND ps.rilevato_il = latest.m
            """
        ).fetchall()
    return [
        (r["codice_istat"], r["piattaforma"] or "?", bool(r["piattaforma_at"]))
        for r in righe
    ]


def campiona(
    db: Path, *, per_famiglia: int, seed: int
) -> list[ComuneCampione]:
    """Campione stratificato: fino a ``per_famiglia`` comuni per famiglia Base.

    Deterministico dato ``seed``: due sweep sullo stesso DB e seed vedono gli
    stessi comuni (requisito del confronto Fase 1↔Fase 3).
    """
    per_fam: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
    for codice, piattaforma, at in _snapshot_corrente(db):
        per_fam[piattaforma].append((codice, piattaforma, at))
    rng = random.Random(seed)
    campione: list[ComuneCampione] = []
    for famiglia in sorted(per_fam):
        righe = sorted(per_fam[famiglia])
        scelti = righe if len(righe) <= per_famiglia else rng.sample(righe, per_famiglia)
        for codice, piattaforma, at in sorted(scelti):
            campione.append(ComuneCampione(codice, piattaforma, at))
    return campione


# --- misura -------------------------------------------------------------------
def _nuovo_esecutore() -> EsecutoreFetch:
    """Un esecutore per-sweep (rate-limit/budget per dominio).

    Prudente di default: il worker tocca molti comuni, alcuni su host SaaS
    condivisi, quindi l'esecutore ricorda gli host già visti nel lotto. Serve
    sia alla sonda-mappa che alla discovery-servizi, quindi è condiviso.
    """
    return EsecutoreFetch(
        PoliticaFetch(
            intervallo_minimo_s=1.0,
            massimo_per_dominio=50,
            backoff_base_s=60.0,
            backoff_cap_s=3600.0,
        )
    )


def _risolvi_mappa_live(codice_istat: str, *, esecutore):
    """Mappa-connettore del comune: cache prima, sonda live sul miss, MAI scrive.

    ``mappa_connettore()`` scriverebbe la cache dopo la sonda (``_in_cache``):
    qui ricomponiamo i pezzi a mano — ``_da_cache`` poi ``_sonda_mappa`` — così
    la misura resta a scrittura-zero. Ritorna ``(mappa, nota)``: ``mappa`` è
    ``None`` quando il comune è ignoto al registro o il portale non è sondabile,
    con ``nota`` che ne distingue la causa.
    """
    voce = _mappa_da_cache(codice_istat)
    if voce is not None:
        return voce, ""
    comune = comune_per_codice(codice_istat)
    if comune is None:
        return None, "comune_ignoto_al_registro"
    try:
        return _sonda_mappa(comune, esecutore=esecutore), ""
    except ProbeBudgetEsaurito:
        return None, "budget_probe_esaurito"
    except ProbeFallita:
        return None, "portale_non_sondabile"


def _entry_host(connettore, richiesta, mappa) -> str:
    """Host dell'entry-point per la memoria di raggiungibilità (no rete)."""
    key = connettore._service_key(richiesta)
    if key is None:
        return ""
    target = connettore._discovery_target(mappa, key)
    return target.official_host if target else ""


def _diagnostica_affidabile(
    connettore, richiesta, mappa, *, tentativi, backoff_s, host_raggiungibili
) -> tuple[object, str]:
    """``diagnostica`` con retry controllato dello STESSO endpoint sul 0-grezzi.

    Separa l'endpoint muto (transient/infra) dall'assenza reale. Ritorna
    ``(diagnostica, nota)`` con ``nota``:

    - ``""`` — segnale al primo colpo (grezzi>0 / confermati>0 / target assente);
    - ``"assenza_reale"`` — entry risponde ma 0 candidati (servizio non pubblicato);
    - ``"endpoint_muto"`` — entry non risponde dopo i retry (transient/infra);
    - ``"transient_recuperato"`` — un retry ha recuperato grezzi/confermati.

    ``host_raggiungibili`` memoizza SOLO i positivi (un host che risponde resta
    affidabile nel lotto); il muto non si memoizza — può recuperare. Zero scritture.
    """
    diag = connettore.diagnostica(richiesta, mappa=mappa)
    if not diag.target_presente or diag.grezzi > 0 or diag.confermati > 0:
        return diag, ""

    host = _entry_host(connettore, richiesta, mappa)
    raggiungibile = host_raggiungibili.get(host)
    if raggiungibile is None:
        raggiungibile = connettore.entry_raggiungibile(richiesta, mappa=mappa)
        if raggiungibile:
            host_raggiungibili[host] = True
    if raggiungibile:
        # Endpoint OK + 0 candidati = assenza reale: nessun retry (non c'è nulla
        # da recuperare, ritentare sarebbe solo carico inutile sull'host).
        return diag, "assenza_reale"

    # Entry muto: candidato transient. Retry con backoff esponenziale; un recupero
    # dimostra che era rumore, non assenza.
    for tentativo in range(tentativi):
        if backoff_s:
            time.sleep(backoff_s * (2 ** tentativo))
        ridiag = connettore.diagnostica(richiesta, mappa=mappa)
        if ridiag.grezzi > 0 or ridiag.confermati > 0:
            return ridiag, "transient_recuperato"
        diag = ridiag
    return diag, "endpoint_muto"


def _misura_via_retrieve(connettore, richiesta, mappa, _riga, nota_fp: str) -> Misura:
    """Misura un connettore privo di ``diagnostica`` via ``retrieve`` diretto.

    Read-only: il write-back sta nel resolver (``service_cache.salva`` dopo il
    retrieve), che qui NON chiamiamo — invochiamo il connettore direttamente.
    Mappa ``ConnectorResult.status`` sugli esiti; l'ambiguità ≥2 è collassata dal
    connettore in NOT_FOUND (limite noto), perciò annotata ``via_retrieve``.
    """
    res = connettore.retrieve(richiesta, mappa=mappa)
    n = len(res.service_references)
    if res.status is DataStatus.FULFILLED and n == 1:
        return _riga(ESITO_FULFILLED, confermati=1, note=nota_fp)
    if res.status is DataStatus.FULFILLED and n >= 2:
        return _riga(ESITO_AMBIGUITA, confermati=n, note=nota_fp)
    if res.status is DataStatus.NOT_SUPPORTED:
        # La famiglia non serve questa chiave su questo comune (variant B/URP):
        # stesso significato di ``target_assente`` nel path diagnostica.
        return _riga(ESITO_CONNETTORE_NON_DISPONIBILE,
                     note=_giunta(nota_fp, "target_assente"))
    # NOT_FOUND (0 confermati, oppure ≥2 collassati): assenza onesta lato connettore.
    return _riga(ESITO_FONTE_ASSENTE, note=_giunta(nota_fp, "via_retrieve"))


def _giunta(*parti: str) -> str:
    """Unisce le note non vuote con uno spazio (helper condiviso)."""
    return " ".join(p for p in parti if p)


def misura_coppia(
    comune: ComuneCampione,
    probe: Probe,
    *,
    registry,
    esecutore,
    tentativi: int = _RETRY_ENDPOINT,
    backoff_s: float = _BACKOFF_S,
    host_raggiungibili: dict[str, bool] | None = None,
    catalog_registry: ConnectorRegistry | None = None,
) -> Misura:
    """Misura una singola ``(comune, probe)`` — nessuna scrittura.

    Ordine (resolver completo): tier cache → catalogo (``_risolvi_da_catalogo``,
    registry isolato, zero-rete) e solo sul suo miss il tier live — sonda-mappa
    sul cache-miss (``_risolvi_mappa_live``) + discovery ``diagnostica`` con
    retry/backoff (``_diagnostica_affidabile``), oppure ``retrieve`` read-only per
    i connettori privi di ``diagnostica``. Il registro è cache-only su disco.
    ``catalog_registry`` sovrascrive il registry isolato del probe (per i test).
    """
    if host_raggiungibili is None:
        host_raggiungibili = {}
    def _riga(esito: str, *, grezzi=0, filtrati=0, confermati=0, note="",
              provenienza=PROV_LIVE) -> Misura:
        return Misura(
            codice_istat=comune.codice_istat,
            base_famiglia=comune.base_famiglia,
            at_presente=comune.at_presente,
            probe_id=probe.probe_id,
            raw=probe.raw,
            atteso=probe.atteso.value if probe.atteso else None,
            riconosciuto=riconosciuto.value if riconosciuto else None,
            recognizer_ok=recognizer_ok,
            esito=esito,
            grezzi=grezzi,
            filtrati=filtrati,
            confermati=confermati,
            note=note,
            provenienza=provenienza,
        )

    riconosciuto = riconosci_service_key(probe.raw)
    recognizer_ok = riconosciuto == probe.atteso

    if riconosciuto is None:
        # Onesto solo se il probe era fuori-vocabolario; altrimenti è un miss di
        # riconoscimento deterministico (materiale Fase 2), annotato ma non forzato.
        nota = "" if probe.atteso is None else "miss_riconoscimento"
        return _riga(ESITO_CHIAVE_NON_RICONOSCIUTA, note=nota, provenienza=PROV_NESSUNA)

    nota_fp = "" if recognizer_ok else "falso_positivo_riconoscimento"

    richiesta = service_request(
        source_id=comune.codice_istat,
        service_key=riconosciuto,
        namespace="measure",
    )

    # Tier cache → catalogo (zero-rete, zero-write): ISTAT-keyed, va PRIMA della
    # sonda-mappa così un comune servito da un adapter standalone via catalogo non
    # cade in ``comune_non_risolto``. Un hit è per costruzione exactly-one (il gate
    # di promozione ha già applicato I-1) → fulfilled con la provenienza del tier.
    risolto = _risolvi_da_catalogo(richiesta, registry_isolato=catalog_registry)
    if risolto is not None:
        prov = PROV_CATALOG if risolto.connector.name == _CATALOG_CONNECTOR.name else PROV_CACHE
        return _riga(ESITO_FULFILLED, confermati=1, note=nota_fp, provenienza=prov)

    mappa, nota_mappa = _risolvi_mappa_live(comune.codice_istat, esecutore=esecutore)
    if mappa is None:
        return _riga(ESITO_COMUNE_NON_RISOLTO, note=(nota_fp or nota_mappa))

    # platform_id per il gate connettore. Il registro data-live NON è popolato a
    # livello nazionale (solo i comuni già passati da uno sweep), quindi la fonte
    # consistente è la famiglia del CENSIMENTO (``storico.db``), le cui stringhe
    # coincidono coi ``_PIATTAFORME`` dei connettori. Il registro, se presente,
    # ha la precedenza (è ciò che userebbe il runtime).
    record = leggi_registro(comune.codice_istat)
    platform_id = (record.piattaforma if record else "") or comune.base_famiglia
    connettore = registry.resolve(request=richiesta, platform_id=platform_id)
    if connettore is None:
        return _riga(ESITO_CONNETTORE_NON_DISPONIBILE, note=(nota_fp or "no_connettore"))

    # Connettore senza discovery diagnostica (es. Magnolia, adapter su ``retrieve``):
    # niente bucket grezzi/filtrati, misura read-only via ``retrieve`` diretto.
    if not hasattr(connettore, "diagnostica"):
        return _misura_via_retrieve(connettore, richiesta, mappa, _riga, nota_fp)

    diag, nota_endpoint = _diagnostica_affidabile(
        connettore, richiesta, mappa,
        tentativi=tentativi, backoff_s=backoff_s, host_raggiungibili=host_raggiungibili,
    )
    if not diag.target_presente:
        return _riga(
            ESITO_CONNETTORE_NON_DISPONIBILE,
            grezzi=diag.grezzi,
            filtrati=diag.filtrati,
            confermati=diag.confermati,
            note=(nota_fp or "target_assente"),
        )

    def _nota(*parti: str) -> str:
        return " ".join(p for p in parti if p)

    if diag.confermati == 1:
        return _riga(ESITO_FULFILLED, grezzi=diag.grezzi, filtrati=diag.filtrati,
                     confermati=diag.confermati, note=_nota(nota_fp, nota_endpoint))
    if diag.confermati >= 2:
        return _riga(ESITO_AMBIGUITA, grezzi=diag.grezzi, filtrati=diag.filtrati,
                     confermati=diag.confermati, note=_nota(nota_fp, nota_endpoint))
    # 0 confermati: endpoint muto (transient) vs assenza reale (servizio non pubblicato).
    if nota_endpoint == "endpoint_muto":
        return _riga(ESITO_ENDPOINT_MUTO, grezzi=diag.grezzi, filtrati=diag.filtrati,
                     confermati=diag.confermati, note=_nota(nota_fp, "endpoint_muto"))
    return _riga(ESITO_FONTE_ASSENTE, grezzi=diag.grezzi, filtrati=diag.filtrati,
                 confermati=diag.confermati, note=_nota(nota_fp, nota_endpoint or "assenza_reale"))


# --- checkpoint / resume ------------------------------------------------------
def _carica_fatte(checkpoint: Path) -> set[tuple[str, str]]:
    """Coppie ``(comune, probe)`` già nel checkpoint, per il resume."""
    fatte: set[tuple[str, str]] = set()
    if not checkpoint.exists():
        return fatte
    for linea in checkpoint.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            obj = json.loads(linea)
            fatte.add((obj["codice_istat"], obj["probe_id"]))
        except (json.JSONDecodeError, KeyError):
            continue  # riga corrotta: la si rimisura, non blocca il resume
    return fatte


def _append_checkpoint(checkpoint: Path, misura: Misura) -> None:
    with checkpoint.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(misura.to_json(), ensure_ascii=False) + "\n")


# --- report -------------------------------------------------------------------
def _leggi_misure(checkpoint: Path) -> list[dict]:
    righe: list[dict] = []
    for linea in checkpoint.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea:
            righe.append(json.loads(linea))
    return righe


def costruisci_report(checkpoint: Path) -> dict:
    """Aggregato dal checkpoint: esiti totali, per famiglia Base, per tag AT,
    e i segnali di riconoscimento (miss / falsi positivi) per la Fase 2.
    """
    misure = _leggi_misure(checkpoint)
    tot = Counter(m["esito"] for m in misure)
    per_famiglia: dict[str, Counter] = defaultdict(Counter)
    per_at: dict[str, Counter] = defaultdict(Counter)
    for m in misure:
        per_famiglia[m["base_famiglia"]][m["esito"]] += 1
        per_at["at" if m["at_presente"] else "no_at"][m["esito"]] += 1
    # Il bucket grezzo `chiave_non_riconosciuta` mescola due cose opposte: i probe
    # fuori-vocabolario deliberati (atteso=None: NON è mancata copertura, è il
    # controllo che regge) e gli eventuali miss di riconoscimento (atteso!=None,
    # materiale Fase 2). Vanno separati o il totale inganna la review.
    cnr = [m for m in misure if m["esito"] == ESITO_CHIAVE_NON_RICONOSCIUTA]
    chiave_attesa = sum(1 for m in cnr if m["atteso"] is None)
    # `comune_non_risolto` idem: distinguere portale non sondabile (miss di rete
    # reale) da comune ignoto al registro o budget esaurito.
    cnr_cause = Counter(
        m["note"] for m in misure if m["esito"] == ESITO_COMUNE_NON_RISOLTO
    )
    # `fonte_assente` ora porta la causa nella nota: assenza_reale (endpoint OK,
    # 0 candidati) vs residui. E i recuperi transient (0-grezzi diventato
    # grezzi>0 dopo un retry) misurano quanto del vecchio fonte_assente era rumore.
    fa_cause = Counter(
        (m["note"] or "assenza_reale")
        for m in misure if m["esito"] == ESITO_FONTE_ASSENTE
    )
    transient_recuperati = sum(
        1 for m in misure if "transient_recuperato" in (m["note"] or "")
    )
    # Copertura onesta: denominatore = solo probe riconoscibili (atteso!=None),
    # così i fuori-vocabolario non gonfiano né il numeratore né il totale.
    reali = [m for m in misure if m["atteso"] is not None]
    esiti_riconoscibili = Counter(m["esito"] for m in reali)
    # Provenienza dei fulfilled riconoscibili (asse ortogonale all'esito): un
    # ``fulfilled`` da catalogo (zero-rete) non equivale a uno scoperto dal vivo.
    # ``or PROV_LIVE`` copre i checkpoint pre-tier (senza campo provenienza): erano
    # tutti misurati dal vivo, quindi l'assenza del campo significa ``live``.
    fulfilled_per_provenienza = Counter(
        (m.get("provenienza") or PROV_LIVE)
        for m in reali
        if m["esito"] == ESITO_FULFILLED
    )
    miss_riconoscimento = [
        {"codice_istat": m["codice_istat"], "probe_id": m["probe_id"], "raw": m["raw"]}
        for m in misure
        if m["note"] == "miss_riconoscimento"
    ]
    falsi_positivi = [
        {"codice_istat": m["codice_istat"], "probe_id": m["probe_id"], "raw": m["raw"],
         "riconosciuto": m["riconosciuto"]}
        for m in misure
        if m["note"] == "falso_positivo_riconoscimento"
    ]
    comuni = {m["codice_istat"] for m in misure}
    return {
        "coppie_misurate": len(misure),
        "coppie_riconoscibili": len(reali),
        "comuni": len(comuni),
        "esiti_totali": dict(tot),
        "esiti_riconoscibili": dict(esiti_riconoscibili),
        "fulfilled_per_provenienza": dict(fulfilled_per_provenienza),
        "chiave_non_riconosciuta_attesa": chiave_attesa,
        "comune_non_risolto_per_causa": dict(cnr_cause),
        "fonte_assente_per_causa": dict(fa_cause),
        "transient_recuperati": transient_recuperati,
        "per_famiglia": {k: dict(v) for k, v in sorted(per_famiglia.items())},
        "per_superficie_at": {k: dict(v) for k, v in sorted(per_at.items())},
        "recognizer_miss": miss_riconoscimento,
        "recognizer_falsi_positivi": falsi_positivi,
        "nota_sp": (
            "SP (service-portal) non è censito per-comune: esiste solo come "
            "provenienza per-ServiceReference dopo la risoluzione, che questo "
            "sweep non persiste. Non misurato qui per scelta."
        ),
    }


def _stampa_report(report: dict) -> None:
    print("\n=== SWEEP DI MISURA — risoluzione servizi (Fase 1) ===")
    print(
        f"coppie misurate: {report['coppie_misurate']}  |  comuni: {report['comuni']}  "
        f"|  di cui riconoscibili: {report.get('coppie_riconoscibili', 0)}"
    )
    attesa = report.get("chiave_non_riconosciuta_attesa", 0)
    print(
        "\nesiti (denominatore = probe riconoscibili; i probe fuori-vocabolario\n"
        f"sono {attesa} `chiave_non_riconosciuta` ATTESI, esclusi dal conteggio):"
    )
    prov = report.get("fulfilled_per_provenienza", {})
    for esito in _ESITI:
        if esito == ESITO_CHIAVE_NON_RICONOSCIUTA:
            continue  # sotto, separato attesi vs miss
        print(f"  {esito:<28} {report.get('esiti_riconoscibili', {}).get(esito, 0)}")
        if esito == ESITO_FULFILLED and prov:
            dettaglio = "  ".join(
                f"{tier}={prov[tier]}" for tier in (PROV_CATALOG, PROV_CACHE, PROV_LIVE)
                if prov.get(tier)
            )
            print(f"  {'  └ per provenienza':<28} {dettaglio}")
    print(
        f"  {'chiave_non_riconosciuta':<28} "
        f"attesi={attesa}  miss_reali={len(report['recognizer_miss'])}"
    )
    causa = report.get("comune_non_risolto_per_causa", {})
    if causa:
        print("\ncomune_non_risolto per causa:")
        for nota, n in sorted(causa.items(), key=lambda kv: -kv[1]):
            print(f"  {nota or '(cache-hit imprevisto)':<28} {n}")
    fa_causa = report.get("fonte_assente_per_causa", {})
    if fa_causa:
        print("\nfonte_assente per causa (assenza reale vs residui):")
        for nota, n in sorted(fa_causa.items(), key=lambda kv: -kv[1]):
            print(f"  {nota or 'assenza_reale':<28} {n}")
    rec = report.get("transient_recuperati", 0)
    print(
        f"\nendpoint_muto (transient/infra, NON assenza): "
        f"{report.get('esiti_riconoscibili', {}).get(ESITO_ENDPOINT_MUTO, 0)}"
        f"  |  transient recuperati dal retry: {rec}"
    )
    print("\nper famiglia Base:")
    for fam, conteggi in report["per_famiglia"].items():
        pezzi = "  ".join(f"{e}={conteggi.get(e, 0)}" for e in _ESITI if conteggi.get(e))
        print(f"  {fam:<16} {pezzi}")
    miss = report["recognizer_miss"]
    fp = report["recognizer_falsi_positivi"]
    if miss:
        print(f"\n⚠ miss di riconoscimento (Fase 2): {len(miss)}")
        for m in miss[:10]:
            print(f"    {m['raw']!r} @ {m['codice_istat']}")
    if fp:
        print(f"\n⚠ falsi positivi di riconoscimento (Fase 2): {len(fp)}")
        for m in fp[:10]:
            print(f"    {m['raw']!r} → {m['riconosciuto']} @ {m['codice_istat']}")
    print(f"\n{report['nota_sp']}\n")


# --- orchestrazione -----------------------------------------------------------
def esegui(
    *,
    db: Path,
    out: Path,
    per_famiglia: int,
    seed: int,
    probes: Sequence[Probe] = GOLDEN,
    limite_comuni: int | None = None,
    tentativi: int = _RETRY_ENDPOINT,
    backoff_s: float = _BACKOFF_S,
) -> dict:
    """Esegue lo sweep di misura e ritorna il report. Nessuna scrittura fuori
    da ``out`` (checkpoint + report). Riprende dal checkpoint esistente.
    """
    out.mkdir(parents=True, exist_ok=True)
    checkpoint = out / "checkpoint.jsonl"
    campione = campiona(db, per_famiglia=per_famiglia, seed=seed)
    if limite_comuni is not None:
        campione = campione[:limite_comuni]
    fatte = _carica_fatte(checkpoint)
    esecutore = _nuovo_esecutore()
    registry = default_service_registry(esecutore)
    da_fare = [
        (c, p) for c in campione for p in probes if (c.codice_istat, p.probe_id) not in fatte
    ]
    print(
        f"campione: {len(campione)} comuni × {len(probes)} probe = "
        f"{len(campione) * len(probes)} coppie; già fatte: {len(fatte)}; "
        f"da misurare ora: {len(da_fare)}"
    )
    # Memoria di raggiungibilità per-host, condivisa nel lotto: un host che ha
    # risposto una volta non si ri-sonda (positivo stabile); il muto non si cachea.
    host_raggiungibili: dict[str, bool] = {}
    for i, (comune, probe) in enumerate(da_fare, 1):
        misura = misura_coppia(
            comune, probe, registry=registry, esecutore=esecutore,
            tentativi=tentativi, backoff_s=backoff_s,
            host_raggiungibili=host_raggiungibili,
        )
        _append_checkpoint(checkpoint, misura)
        if i % 25 == 0 or i == len(da_fare):
            print(f"  … {i}/{len(da_fare)}  (ultimo: {misura.esito} @ {comune.codice_istat})")
    report = costruisci_report(checkpoint)
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _stampa_report(report)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="measurement_sweep",
        description="Sweep di MISURA della risoluzione servizi (live-read, zero-write).",
    )
    parser.add_argument("--db", type=Path, default=Path("data/storico.db"),
                        help="storico.db da cui campionare i comuni (default data/storico.db).")
    parser.add_argument("--out", type=Path, default=Path("data/measure"),
                        help="cartella scratch per checkpoint e report (mai il catalogo).")
    parser.add_argument("--per-famiglia", type=int, default=5,
                        help="comuni per famiglia Base nel campione stratificato.")
    parser.add_argument("--seed", type=int, default=42,
                        help="seed del campionamento (riproducibilità Fase 1↔Fase 3).")
    parser.add_argument("--limite-comuni", type=int, default=None,
                        help="tetto opzionale sul numero di comuni (smoke run).")
    parser.add_argument("--solo-report", action="store_true",
                        help="ricostruisce il report dal checkpoint senza misurare.")
    parser.add_argument("--tentativi", type=int, default=_RETRY_ENDPOINT,
                        help="retry dello stesso endpoint sul 0-grezzi (muto vs assenza).")
    parser.add_argument("--backoff-s", type=float, default=_BACKOFF_S,
                        help="backoff base (s) tra i retry; 0 = nessuna attesa.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.solo_report:
        checkpoint = args.out / "checkpoint.jsonl"
        if not checkpoint.exists():
            print(f"nessun checkpoint in {checkpoint}", file=sys.stderr)
            return 1
        _stampa_report(costruisci_report(checkpoint))
        return 0

    esegui(
        db=args.db,
        out=args.out,
        per_famiglia=args.per_famiglia,
        seed=args.seed,
        limite_comuni=args.limite_comuni,
        tentativi=args.tentativi,
        backoff_s=args.backoff_s,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
