"""Universal indirect connector backed by an injectable scrape engine."""

from __future__ import annotations

from datetime import datetime, timezone

from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import AccessMode, FreshnessStatus
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataRequest,
    DataStatus,
    Freshness,
    TransportMeta,
)
from treasureiq.catalog.scraping import ScrapeEngine, ScrapeResult
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore


class WebScrapeConnector:
    name = "web_scrape"
    version = "1"

    def __init__(self, engine: ScrapeEngine | None = None) -> None:
        self.engine = engine

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        return request.capability in {"services", "offices", "contacts", "transparency"}

    def retrieve(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> ConnectorResult:
        engine = self.engine
        if engine is None:
            from treasureiq.catalog.scraping import HtmlScrapeEngine

            engine = HtmlScrapeEngine()
        return self.retrieve_live(request, mappa=mappa, engine=engine)

    def retrieve_live(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        engine: ScrapeEngine,
    ) -> ConnectorResult:
        if request.source_id != mappa.codice_istat:
            raise ValueError("request.source_id does not match the measured source")
        if not mappa.sito:
            return ConnectorResult(
                request_id=request.request_id,
                source_id=request.source_id,
                status=DataStatus.NOT_FOUND,
                access_mode=AccessMode.INDIRECT,
                freshness=Freshness(status=FreshnessStatus.UNKNOWN),
                limitations=("Il comune non ha una fonte web configurata.",),
                connector=ConnectorRef(name=self.name, version=self.version),
            )

        scraped = engine.retrieve(source_url=mappa.sito, request=request)
        records = scraped.records[: request.limits.max_records]
        status = (
            DataStatus.FAILED
            if scraped.status is ScrapeResult.Status.FAILED
            else DataStatus.UNREADABLE
            if scraped.status is ScrapeResult.Status.UNSUPPORTED
            else DataStatus.FULFILLED
            if records
            else DataStatus.EMPTY
        )
        retrieved_at = scraped.retrieved_at or datetime.now(timezone.utc)
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=status,
            access_mode=AccessMode.INDIRECT,
            records=records,
            evidence=scraped.evidence[: request.limits.max_records],
            freshness=Freshness(
                status=FreshnessStatus.LIVE if records else FreshnessStatus.UNKNOWN,
                retrieved_at=retrieved_at,
            ),
            limitations=scraped.limitations,
            transport=TransportMeta(
                requests=scraped.requests,
                bytes=scraped.bytes,
                from_cache=False,
            ),
            connector=ConnectorRef(name=self.name, version=self.version),
            retrieved_at=retrieved_at,
        )
