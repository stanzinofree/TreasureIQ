"""Bridge connector for the measured WordPress-AgID source.

The legacy scanner remains the component that performs the HTTP work. This
connector owns the capability-level projection of its result, so callers can
move to ``ConnectorResult`` without changing the scanner in one risky step.
"""

from __future__ import annotations

from datetime import datetime, timezone

from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import AccessMode, FreshnessStatus
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
    TransportMeta,
)
from treasureiq.catalog.adapters.wordpress_agid import WordPressAgidAdapter
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore, mappa_connettore
from treasureiq.sonda_live import ComuneNoto
from treasureiq.ingest.censimento import _Sonda


class WordPressAgidConnector:
    """Expose one measured WordPress-AgID capability as ``ConnectorResult``."""

    name = "wordpress_agid"
    version = "1"

    def retrieve_live(
        self,
        request: DataRequest,
        *,
        comune: ComuneNoto,
        sonda: _Sonda,
    ) -> ConnectorResult:
        """Run the existing HTTP scanner and expose its result as v1.

        The import is deferred deliberately: the legacy scanner imports the
        v0 connector models, while this module is also imported by the catalog
        package. Keeping the boundary lazy avoids an import cycle during app
        startup.
        """
        from treasureiq.wordpress_agid import leggi_wordpress_agid

        esito = leggi_wordpress_agid(comune, sonda)
        mappa = mappa_connettore(comune.codice_istat)
        if mappa is None:
            raise ValueError("live WordPress scan did not produce a connector map")
        return self.retrieve(request, mappa=mappa, esito=esito)

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        return platform_id == self.name and WordPressAgidAdapter().manifest.supports(
            surface=request.surface.value,
            capability=request.capability,
        )

    def retrieve(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> ConnectorResult:
        if request.source_id != mappa.codice_istat:
            raise ValueError("request.source_id does not match the measured source")

        adapter = WordPressAgidAdapter()
        mode = adapter._access_mode(request.surface, request.capability, mappa, esito)
        records = adapter._records(request.surface, request.capability, mappa, esito)
        records = records[: request.limits.max_records]
        evidence = tuple(
            EvidenceRef(evidence_id=str(record["url"]), field="url")
            for record in records
            if record.get("url")
        )
        freshness_status = (
            FreshnessStatus.FRESH
            if mappa.sondato_il
            else FreshnessStatus.UNKNOWN
        )
        status = (
            DataStatus.NOT_SUPPORTED
            if mode is AccessMode.UNAVAILABLE
            else DataStatus.FULFILLED
            if records
            else DataStatus.EMPTY
        )
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=status,
            access_mode=mode,
            records=tuple(records),
            evidence=evidence,
            freshness=Freshness(
                status=freshness_status,
                retrieved_at=datetime.fromisoformat(mappa.sondato_il),
            ),
            limitations=(
                "L'esito deriva dalla scansione WordPress-AgID misurata; la lettura HTTP è gestita dal legacy scanner.",
            ),
            transport=TransportMeta(from_cache=True),
            connector=ConnectorRef(name=self.name, version=self.version),
            retrieved_at=datetime.now(timezone.utc),
        )
