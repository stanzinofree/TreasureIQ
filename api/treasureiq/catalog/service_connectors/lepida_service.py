"""Lepida/MyPortal (Rete Civica Emilia-Romagna) service connector.

Quinto connettore-servizio, con un confine deliberatamente stretto: **solo** la
Rete Civica di Lepida in Emilia-Romagna (``rete_civica_lepida``, ~70 comuni).
MyPortal è un prodotto multi-regione, ma i tipi di contenuto e il vocabolario
delle schede cambiano per deployment (l'ER pubblica ``rer_schedaservizio``, il
Veneto un tipo proprio con ~149 declinazioni). Questo adapter **non** tocca la
variante veneta: nessun tipo, catalogo o fixture di quella regione — il gate di
piattaforma la lascia fuori per costruzione.

MyPortal è una SPA: l'HTML delle schede è un guscio disegnato nel browser, ma
dietro c'è un'API JSON vera, tutta in ``GET``, raggiungibile dal codice IPA che
sta scritto nella home. La discovery riusa **verbatim** il contratto puro di
``ingest/myportal.py`` (costruzione URL, scelta dei tipi, lettura della pagina):
qui vive solo l'orchestrazione dei fetch e il mapping voce→``ServiceCandidate``.

Flusso di discovery (tre fetch, nessun fan-out sui contenuti):

1. **home → IPA**: ``codice_ipa`` legge il ``C_XXXX`` dalla home (già scaricata
   comunque), ``normalizza_ipa`` lo porta in maiuscolo — MyPortal risponde solo
   così, e a un IPA minuscolo dà ``200`` con zero risultati (un comune che
   *sembra* non pubblicare niente);
2. **default-types → tipi servizio**: ``tipi_candidati`` sceglie i tipi che sono
   schede servizio (in ER uno solo, ``rer_schedaservizio``), invece di indovinare
   un tipo che, se sbagliato, non dà errore ma zero risultati;
3. **/api/content → candidati**: un solo ``GET`` per tipo restituisce l'elenco
   completo delle schede (``pageSize`` ampio, cap difensivo in memoria a valle);
   il termine (ServiceKey) **non** filtra server-side su questo endpoint ``GET``
   — la selezione è a valle, col recogniser condiviso sul titolo.

Nessuna policy per-chiave propria: i titoli delle schede ER confermano la
ServiceKey direttamente (``"Separazione o divorzio davanti all'ufficiale di
stato civile"`` → STATO_CIVILE), quindi vale l'exactly-one-o-NOT_FOUND del
``_ServiceConnectorBase`` senza aggregazioni. Invarianti, host guard, MEDIATED,
opzioni dalla pagina e forma della ``ServiceReference`` sono condivise là.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from treasureiq.catalog.data_contracts import ConnectorRef
from treasureiq.catalog.service_connectors.base import ServiceCandidate, ServiceFetcher
from treasureiq.catalog.service_connectors.connettore_base import (
    DiscoveryTarget,
    _ServiceConnectorBase,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.ingest import myportal
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www

_CONNECTOR = ConnectorRef(name="lepida_service", version="1")

#: Cap difensivo (guardia memoria) sul numero di schede raccolte dagli elenchi.
#: Sta molto sopra il catalogo comunale reale più grande visto in ER (~142): non
#: è una selezione, la conferma esattamente-uno è a valle (``_confermati``). Vale
#: anche come ``pageSize`` dell'elenco, così un solo ``GET`` porta l'intero
#: catalogo e nessuna scheda oltre la prima pagina alfabetica sfugge.
_CAP_DIFENSIVO_SCHEDE = 1000


class _LepidaDiscovery:
    """Scoperta Lepida/MyPortal: home→IPA, tipi servizio, elenco → candidati.

    Net-free rispetto a httpx: usa solo i primitivi guardati del transport comune
    (``leggi_pagina`` per la home HTML, ``scarica_json`` per il JSON REST). Ogni
    URL è costruito dal contratto puro di ``ingest/myportal.py`` (nessuna rotta
    inventata qui); l'unico URL *seguito* è il ``sys_canonical_url`` realmente
    presente nella voce, reso assoluto e sottoposto all'host guard a valle.
    """

    def scopri_servizi(
        self,
        transport: ServiceFetcher,
        *,
        base_url: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        host = urlparse(base_url).netloc
        # 1) IPA dalla home — l'unica pagina che scarichiamo comunque.
        home = transport.leggi_pagina(url=base_url, official_host=host)
        if not home:
            return ()  # home muta → miss onesto (non un catalogo vuoto)
        ipa = myportal.normalizza_ipa(myportal.codice_ipa(home))
        if not ipa:
            return ()  # comune non indirizzabile per questa via: dirlo, non fingere

        # 2) Tipi di contenuto → quelli che sono schede servizio (ER: uno solo).
        tipi_payload = transport.scarica_json(
            url=myportal.url_tipi(base_url, ipa), host_atteso=_host_senza_www(host.lower())
        )
        tipi = myportal.tipi_candidati(tipi_payload)
        if not tipi:
            return ()

        # 3) Un GET di elenco per tipo → candidati, dedotti per id nativo.
        visti: set[str] = set()
        candidati: list[ServiceCandidate] = []
        for tipo in tipi:
            if len(candidati) >= limit:
                break  # cap DIFENSIVO (guardia memoria), non selezione
            risposta = transport.scarica_json(
                url=myportal.url_elenco(base_url, ipa, tipo, quanti=limit),
                host_atteso=_host_senza_www(host.lower()),
            )
            _totale, voci = myportal.leggi_pagina(risposta)
            for voce in voci:
                if len(candidati) >= limit:
                    break
                candidato = self._candidato(voce, base_url)
                if candidato is None or candidato.native_id in visti:
                    continue
                visti.add(candidato.native_id)
                candidati.append(candidato)
        return tuple(candidati)

    @staticmethod
    def _candidato(voce: dict, base_url: str) -> ServiceCandidate | None:
        """Una voce ``/api/content`` → ``ServiceCandidate``, o ``None`` se inadatta.

        ``sourceId`` è l'identità nativa stabile (il titolo cambia, l'id no);
        ``name`` il titolo per il recogniser; ``sys_canonical_url`` la pagina
        pubblica, relativa nel payload e resa assoluta sull'host del comune. Un
        campo assente/malformato scarta la voce (mai coniare un id dal titolo né
        fabbricare un URL, I-2/I-4)."""
        if not isinstance(voce, dict):
            return None
        native_id = str(voce.get("sourceId") or "").strip()
        title = str(voce.get("name") or "").strip()
        attributi = voce.get("attributes")
        canonical = (
            attributi.get("sys_canonical_url") if isinstance(attributi, dict) else None
        )
        if not native_id or not title or not canonical:
            return None
        url = urljoin(base_url, str(canonical))
        try:
            return ServiceCandidate(native_id=native_id, title=title, url=url)
        except (ValueError, TypeError):
            return None


class LepidaServiceConnector(_ServiceConnectorBase):
    """Risolve un ``ServiceKey`` in un ``ServiceReference`` sui portali Lepida/ER.

    Corpo condiviso in ``_ServiceConnectorBase``; qui solo il gate di piattaforma
    (``rete_civica_lepida``), il prefisso ``lepida`` e il target di discovery (la
    home, da cui la strategia ricava l'IPA). Il gate non dipende da
    ``servizi.esposto``/``rest_base`` (concetti WP-REST, assenti su MyPortal):
    basta la piattaforma e un ``sito`` valido.
    """

    name = "lepida_service"
    version = "1"
    _CONNECTOR = _CONNECTOR
    _PIATTAFORME = frozenset({Piattaforma.RETE_CIVICA_LEPIDA.value})
    _PREFISSO = "lepida"
    _PROVIDER_PLATFORM = "lepida"
    _LIMITE_RICERCA = _CAP_DIFENSIVO_SCHEDE

    def _discovery_target(self, mappa, service_key: ServiceKey) -> DiscoveryTarget | None:
        base = _base_con_schema(getattr(mappa, "sito", None))
        if base is None:
            return None  # nessun sito → NOT_SUPPORTED
        # entry = home: la strategia ne ricava l'IPA e compone gli URL MyPortal.
        return DiscoveryTarget(base, service_key.value, urlparse(base).netloc)
