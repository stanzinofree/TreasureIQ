"""Connettore-servizio Magnolia (variant A) sul contratto ``SourceConnector``.

Aggancia al runtime servizi il rail finora standalone di ``magnolia.py``
(``LETTORE_SERVIZI_PER_PIATTAFORMA``, [[magnolia-connettore-standalone]]): un
**wrapper** sul protocol duck-typed ``SourceConnector``, non una subclass di
``_ServiceConnectorBase``. La differenza è deliberata — la base sostituirebbe il
parser Magnolia (categorie REST KIB, paginazione ``pageSize=100``, dedup per URL,
guardia host sibling-SaaS, gate variant B → URP) con la sua pipeline di discovery
+ conferma via recogniser chat. Qui il parser resta **invariato**: il wrapper lo
legge tramite ``leggi_magnolia_servizi`` e proietta il suo esito nel
``ConnectorResult`` che il resolver consuma (cache → catalogo → live).

Confini onesti (I-1/I-2):
- filtro sul solo ``service_key`` richiesto, poi gate **esattamente-1** (0 → miss,
  ≥2 → ambiguo: entrambi ``NOT_FOUND``, mai una scelta implicita);
- ``service_id`` dall'URL nativo del servizio, **mai** dal titolo;
- HTML-scrape → ``AccessMode.MEDIATED`` (mai ``DIRECT``: nessun campo REST tipato);
- variant B / irraggiungibile → esito non-``FULFILLED`` → il resolver ritorna
  ``None`` → ripiego URP onesto, nessun dato coniato.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import (
    CAPABILITY_SERVICES,
    AccessMode,
    ConnectorRef,
    FreshnessStatus,
    Surface,
)
from treasureiq.catalog.data_contracts import (
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
)
from treasureiq.catalog.service_contracts import (
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
    ServiceReference,
)
from treasureiq.connettore import EsitoConnettore
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.magnolia import CONNETTORE_VERSION, leggi_magnolia_servizi
from treasureiq.mappa_connettore import MappaConnettore


def _native_id(url: str) -> str:
    """Id nativo stabile dall'URL servizio — mai dal titolo (I-2).

    Ultimo segmento del path (senza ``.html``) PIÙ la query normalizzata quando
    presente: sul portale SaaS più servizi condividono lo stesso path
    (``.../landingIstanza``) e differiscono solo nel ``?Id=NN``, quindi il solo
    path collisionerebbe due servizi distinti. Chiavi query ordinate → id
    deterministico e indipendente dall'ordine. Serve solo a comporre un
    ``service_id`` univoco, non è un'identità semantica.
    """
    parti = urlsplit(url)
    segmenti = [s for s in parti.path.split("/") if s]
    base = (segmenti[-1] if segmenti else parti.hostname or url).removesuffix(".html")
    coppie = sorted(parse_qsl(parti.query))
    if coppie:
        coda = "-".join(f"{k}={v}" for k, v in coppie)
        base = f"{base}-{coda}" if base else coda
    grezzo = base or (parti.hostname or url)
    # Compatta in un token opaco stabile (niente spazi/simboli nel service_id).
    return re.sub(r"[^A-Za-z0-9._-]+", "-", grezzo).strip("-") or "servizio"


class MagnoliaServiceConnector:
    """``SourceConnector`` che serve un servizio Magnolia variant A dal parser.

    ``lettore`` è iniettabile per i test net-free (stessa firma di
    ``leggi_magnolia_servizi``, che risolve la home da ``storico.db`` e non
    solleva mai). Il connettore non fa rete propria: delega tutto al lettore.
    """

    name = "magnolia_service"
    version = CONNETTORE_VERSION

    _CONNECTOR = ConnectorRef(name="magnolia_service", version=CONNETTORE_VERSION)
    _PROVIDER_PLATFORM = Piattaforma.MAGNOLIA.value
    _PIATTAFORME = frozenset({Piattaforma.MAGNOLIA.value})

    def __init__(self, lettore=leggi_magnolia_servizi) -> None:
        self._lettore = lettore

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        # Solo dati ordinari + capability servizi su una piattaforma Magnolia.
        return (
            request.surface is Surface.ORDINARY_DATA
            and request.capability == CAPABILITY_SERVICES
            and platform_id in self._PIATTAFORME
        )

    def retrieve(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None = None,
    ) -> ConnectorResult:
        now = datetime.now(timezone.utc)

        if request.source_id != mappa.codice_istat:
            # La fonte misurata dev'essere quella richiesta: un mismatch conierebbe
            # un'identità falsa (stesso invariante della base).
            raise ValueError("request.source_id does not match the measured source")

        service_key = self._service_key(request)
        if service_key is None:
            return self._esito(request, now, DataStatus.NOT_FOUND, AccessMode.UNAVAILABLE)

        letto = self._lettore(mappa.codice_istat)

        if letto.esito in ("irraggiungibile", "variante_non_strutturata"):
            # Nessun catalogo strutturato da servire: sito muto o variant B (URP).
            # Miss onesto, non un errore — il resolver ripiega su URP.
            return self._esito(request, now, DataStatus.NOT_SUPPORTED, AccessMode.UNAVAILABLE)

        confermati = [
            s for s in letto.servizi if s.service_key == service_key.name
        ]
        if len(confermati) != 1:
            # 0 → miss onesto; ≥2 → ambiguo, scelta di un livello superiore (I-1).
            return self._esito(request, now, DataStatus.NOT_FOUND, AccessMode.MEDIATED)

        servizio = confermati[0]
        url = urljoin(letto.home, servizio.url)  # assolutizza gli href on-site
        opzione = ServiceAccessOption(
            mode=ServiceAccessMode.INFORMATION,
            url=url,
            source_url=url,
        )
        reference = ServiceReference(
            service_id=f"{request.source_id}:magnolia:{_native_id(url)}",
            title=servizio.titolo,
            source_url=url,
            options=(opzione,),
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
            evidence=(EvidenceRef(evidence_id=str(url), field="url"),),
            freshness=Freshness(status=FreshnessStatus.LIVE, retrieved_at=now),
            connector=self._CONNECTOR,
            retrieved_at=now,
        )

    @staticmethod
    def _service_key(request: DataRequest) -> ServiceKey | None:
        raw = request.selection.get("service_key")
        if not raw:
            return None
        try:
            return ServiceKey(raw)
        except ValueError:
            return None

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
