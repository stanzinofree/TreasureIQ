"""Base condivisa dei connettori-servizio (Ramo 3, §3.3).

Il corpo del pilota WP/AgID — gate su ``source_id``, conferma via recogniser
condiviso, opzioni dalla pagina servizio, forma del ``ServiceReference`` e del
``ConnectorResult`` — è **piattaforma-agnostico**.  Vive qui.  WP e ComWeb sono
sottotipi che differiscono solo in:

- ``supports()`` — il gate di piattaforma (``_PIATTAFORME``);
- il prefisso di ``service_id`` (``_PREFISSO``: ``wp`` / ``comweb``);
- ``provider_platform`` (``_PROVIDER_PLATFORM``);
- il **target di discovery** (``_discovery_target``): entry-point + termine
  calcolati da ``mappa``.  È l'unico punto dove la piattaforma è nota — WP compone
  la collezione REST, ComWeb l'indice statico; il ``term`` è la stringa di ricerca
  per WP, lo slug di categoria per ComWeb.

Le invarianti I-1…I-6 (esattamente-uno-o-NOT_FOUND, id mai dal titolo, MEDIATED,
niente URL inventati, host guard, conferma solo via recogniser) sono imposte qui,
una volta per tutte le famiglie.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple
from urllib.parse import urlparse

from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import (
    AccessMode,
    CAPABILITY_SERVICES,
    FreshnessStatus,
    Surface,
)
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
)
from treasureiq.catalog.service_connectors.base import ServiceCandidate, ServiceFetcher
from treasureiq.catalog.service_contracts import (
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
    ServiceReference,
)
from treasureiq.catalog.service_page import EvidenceKind, leggi_pagina_servizio
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import _host_senza_www


class DiscoveryTarget(NamedTuple):
    """Dove e cosa cercare, deciso dal sottotipo a partire dalla ``mappa``.

    ``entry_url`` è l'unico URL costruito dal connettore (root REST per WP, indice
    servizi per ComWeb); ``term`` è la stringa di ricerca (WP) o lo slug di
    categoria da seguire (ComWeb); ``official_host`` è l'host su cui la discovery e
    l'host guard sono ancorati.
    """

    entry_url: str
    term: str
    official_host: str


class DiagnosticaConnettore(NamedTuple):
    """Conteggi read-only di una risoluzione, per lo sweep di misura (Fase 1).

    ``retrieve`` collassa 0 e ≥2 confermati nello stesso ``NOT_FOUND``: per
    misurare *onestamente* «miss» (0) contro «ambiguo» (≥2) serve il conteggio,
    che qui viene esposto senza coniare identità né scrivere nulla.

    - ``chiave_valida``: la request portava una ``ServiceKey`` in vocabolario;
    - ``target_presente``: la piattaforma ha un entry-point per quella key
      (``False`` → la famiglia non serve questa key su questo comune);
    - ``grezzi`` / ``filtrati`` / ``confermati``: candidati a ogni stadio della
      pipeline di discovery (discovery → filtro class-aware → gate host+recogniser).
    """

    chiave_valida: bool
    target_presente: bool
    grezzi: int
    filtrati: int
    confermati: int


class _ServiceConnectorBase:
    """Risolve un ``ServiceKey`` in **esattamente un** ``ServiceReference``.

    Sottoclassare e impostare gli attributi di classe più ``_discovery_target``.
    Tutto il resto (conferma, opzioni, esito) è condiviso e non va sovrascritto.
    """

    #: Impostati dal sottotipo.
    name: str = ""
    version: str = ""
    _CONNECTOR: ConnectorRef
    _PIATTAFORME: frozenset[str] = frozenset()
    _PREFISSO: str = ""
    _PROVIDER_PLATFORM: str = ""
    #: Tetto di candidati raccolti dalla discovery (anti fan-out, configurabile).
    _LIMITE_RICERCA: int = 20

    def __init__(self, fetcher: ServiceFetcher) -> None:
        self._fetcher = fetcher

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        # Barriera vs il ServicePortalConnettore: solo dati ordinari + capability
        # servizi su una piattaforma di questa famiglia.
        return (
            request.surface is Surface.ORDINARY_DATA
            and request.capability == CAPABILITY_SERVICES
            and platform_id in self._PIATTAFORME
        )

    def retrieve(
        self,
        request: DataRequest,
        *,
        mappa,
        esito: EsitoConnettore | None,
    ) -> ConnectorResult:
        now = datetime.now(timezone.utc)

        if request.source_id != mappa.codice_istat:
            # La fonte misurata dev'essere quella richiesta: il service_id nasce
            # da source_id, un mismatch conierebbe un'identità falsa.
            raise ValueError("request.source_id does not match the measured source")

        service_key = self._service_key(request)
        if service_key is None:
            return self._esito(request, now, DataStatus.NOT_FOUND, AccessMode.UNAVAILABLE)

        target = self._discovery_target(mappa, service_key)
        if target is None:
            # Nessun sito o piattaforma non servibile per questo comune.
            return self._esito(request, now, DataStatus.NOT_SUPPORTED, AccessMode.UNAVAILABLE)

        candidati = self._fetcher.scopri_servizi(
            base_url=target.entry_url,
            term=target.term,
            limit=self._LIMITE_RICERCA,
        )
        # Filtro class-aware PRIMA del gate host/recogniser e del gate 0/≥2: una
        # famiglia che espone una classe di contenuto nativa (OpenPA/eZ Find)
        # scarta qui le classi non ammesse per la key (notizie, canali, enti), così
        # il gate esattamente-1 vede solo candidati della classe giusta.  Default
        # no-op: le famiglie senza classe (WP, ComWeb) passano invariate.
        candidati = self._filtra_candidati(candidati, service_key)
        confermati = self._confermati(candidati, service_key, target.official_host)
        if len(confermati) != 1:
            # 0 → miss onesto; ≥2 → ambiguo, la scelta è di un livello superiore,
            # mai una scelta implicita qui (I-1).
            return self._esito(request, now, DataStatus.NOT_FOUND, AccessMode.MEDIATED)

        candidato = confermati[0]
        opzioni = self._opzioni(candidato, target.official_host)
        reference = ServiceReference(
            service_id=f"{request.source_id}:{self._PREFISSO}:{candidato.native_id}",
            title=candidato.title,
            source_url=candidato.url,
            options=opzioni,
            discovered_from=Surface.ORDINARY_DATA,
            provider_platform=self._PROVIDER_PLATFORM,
            discovered_at=now,
        )
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=DataStatus.FULFILLED,
            access_mode=AccessMode.MEDIATED,
            service_references=(reference,),
            evidence=tuple(
                EvidenceRef(evidence_id=str(opzione.url), field="url") for opzione in opzioni
            ),
            freshness=Freshness(status=FreshnessStatus.LIVE, retrieved_at=now),
            connector=self._CONNECTOR,
            retrieved_at=now,
        )

    def diagnostica(self, request: DataRequest, *, mappa) -> DiagnosticaConnettore:
        """Misura read-only dell'esito di risoluzione (sweep di misura, Fase 1).

        Esegue la STESSA discovery live di ``retrieve`` — discovery + filtro
        class-aware + gate host/recogniser — e riporta i conteggi dei candidati
        a ogni stadio, così un livello superiore distingue «miss» (0 confermati)
        da «ambiguo» (≥2), che ``retrieve`` collassa entrambi in ``NOT_FOUND``.
        Non chiama ``_opzioni`` (nessuna lettura di pagina extra), non conia una
        ``ServiceReference`` e non scrive nulla: nessun effetto sul path live.
        """
        if request.source_id != mappa.codice_istat:
            raise ValueError("request.source_id does not match the measured source")
        service_key = self._service_key(request)
        if service_key is None:
            return DiagnosticaConnettore(False, False, 0, 0, 0)
        target = self._discovery_target(mappa, service_key)
        if target is None:
            return DiagnosticaConnettore(True, False, 0, 0, 0)
        grezzi = self._fetcher.scopri_servizi(
            base_url=target.entry_url,
            term=target.term,
            limit=self._LIMITE_RICERCA,
        )
        filtrati = self._filtra_candidati(grezzi, service_key)
        confermati = self._confermati(filtrati, service_key, target.official_host)
        return DiagnosticaConnettore(
            True, True, len(grezzi), len(filtrati), len(confermati)
        )

    def entry_raggiungibile(self, request: DataRequest, *, mappa) -> bool | None:
        """Sonda read-only la sola raggiungibilità dell'``entry_url``.

        Serve allo strumento di misura per distinguere, quando ``diagnostica``
        ritorna 0 grezzi, un endpoint **muto** (fetch fallito / vuoto = transient
        o infra) da una **assenza reale** (endpoint OK, 0 candidati). Fetcha solo
        l'entry-point (indice REST/servizi) e riporta se ha risposto — nessuna
        discovery, nessun filtro, nessuna reference, nessuna scrittura.

        Ritorna ``None`` se non c'è target (chiave non valida o sito assente):
        in quel caso la (non-)raggiungibilità non è definita.
        """
        service_key = self._service_key(request)
        if service_key is None:
            return None
        target = self._discovery_target(mappa, service_key)
        if target is None:
            return None
        pagina = self._fetcher.leggi_pagina(
            url=target.entry_url, official_host=target.official_host
        )
        return bool(pagina)

    # -- hook per-famiglia -------------------------------------------------

    def _discovery_target(self, mappa, service_key: ServiceKey) -> DiscoveryTarget | None:
        """Entry-point + termine per questa famiglia, o ``None`` per gate fallito
        (nessun sito / piattaforma non servibile) → ``NOT_SUPPORTED``."""
        raise NotImplementedError

    # -- internals condivisi ----------------------------------------------

    @staticmethod
    def _service_key(request: DataRequest) -> ServiceKey | None:
        raw = request.selection.get("service_key")
        if not raw:
            return None
        try:
            return ServiceKey(raw)
        except ValueError:
            return None

    def _filtra_candidati(
        self,
        candidati: tuple[ServiceCandidate, ...],
        service_key: ServiceKey,
    ) -> tuple[ServiceCandidate, ...]:
        """Hook per-famiglia: restringe i candidati PRIMA del gate host/recogniser.

        Default no-op — le famiglie senza una classe di contenuto nativa (WP,
        ComWeb) non filtrano nulla qui.  OpenPA lo sovrascrive con un'allow-list
        per ``classIdentifier``.  Può solo restringere: non conia mai candidati,
        quindi non introduce falsi confermati (al più più ``vuoto`` onesti)."""
        return candidati

    @staticmethod
    def _confermati(
        candidati: tuple[ServiceCandidate, ...],
        service_key: ServiceKey,
        official_host: str,
    ) -> tuple[ServiceCandidate, ...]:
        # Un candidato dev'essere (a) sull'host DEL comune e (b) confermare la key
        # richiesta col recogniser CONDIVISO sul titolo — stessa key, non ambiguo
        # (il recogniser torna None sul conflitto), nessun nearest-neighbour.
        # L'host guard è qui, non solo nel fetcher: un payload potrebbe portare un
        # url a un host esterno e quell'URL non deve mai diventare source_url o
        # opzione.  Chi fallisce un check è scartato (0 confermati → NOT_FOUND).
        host_ufficiale = _host_senza_www(official_host.lower())
        return tuple(
            c
            for c in candidati
            if _host_senza_www(urlparse(str(c.url)).netloc.lower()) == host_ufficiale
            and riconosci_service_key(c.title) is service_key
        )

    def _opzioni(
        self, candidato: ServiceCandidate, official_host: str
    ) -> tuple[ServiceAccessOption, ...]:
        # INFORMATION è sempre presente: la pagina servizio è la fonte citata.
        opzioni: list[ServiceAccessOption] = [
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION,
                url=candidato.url,
                source_url=candidato.url,
            )
        ]
        html = self._fetcher.leggi_pagina(url=str(candidato.url), official_host=official_host)
        if not html:
            return tuple(opzioni)

        pagina = leggi_pagina_servizio(
            html, page_url=str(candidato.url), official_host=official_host
        )
        for link in pagina.links:
            if link.kind is EvidenceKind.DOWNLOAD:
                opzioni.append(
                    ServiceAccessOption(
                        mode=ServiceAccessMode.DOWNLOAD,
                        url=link.url,
                        source_url=candidato.url,
                    )
                )
            elif link.kind is EvidenceKind.AUTHENTICATED_ONLINE:
                opzioni.append(
                    ServiceAccessOption(
                        mode=ServiceAccessMode.AUTHENTICATED_ONLINE,
                        url=link.url,
                        source_url=candidato.url,
                        requires_authentication=True,
                        authentication=link.authentication,
                    )
                )
        return tuple(opzioni)

    def _esito(
        self,
        request: DataRequest,
        now: datetime,
        status: DataStatus,
        access_mode: AccessMode,
    ) -> ConnectorResult:
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=status,
            access_mode=access_mode,
            freshness=Freshness(status=FreshnessStatus.LIVE, retrieved_at=now),
            connector=self._CONNECTOR,
            retrieved_at=now,
        )
