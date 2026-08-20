from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessMode,
    DataRequest,
    FreshnessPolicy,
    ScrapeResult,
    Surface,
    WebScrapeConnector,
)
from treasureiq.catalog.data_contracts import EvidenceRef
from treasureiq.mappa_connettore import MappaConnettore


class _Engine:
    def retrieve(self, *, source_url: str, request: DataRequest) -> ScrapeResult:
        assert source_url == "https://comune.example"
        return ScrapeResult(
            records=({"nome": "Anagrafe", "url": "https://comune.example/anagrafe"},),
            evidence=(EvidenceRef(evidence_id="https://comune.example/anagrafe", field="url"),),
            retrieved_at=datetime.now(timezone.utc),
            requests=2,
            bytes=512,
        )


def _request() -> DataRequest:
    return DataRequest(
        request_id="req-web",
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        capability="offices",
        freshness=FreshnessPolicy(max_age_seconds=3600),
        manifest_revision=1,
    )


def _mappa(*, sito: str | None = "https://comune.example") -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito=sito,
        sondato_il=datetime.now(timezone.utc).isoformat(),
    )


def test_web_connector_converts_engine_output_to_indirect_result() -> None:
    result = WebScrapeConnector().retrieve_live(_request(), mappa=_mappa(), engine=_Engine())

    assert result.access_mode is AccessMode.INDIRECT
    assert result.records[0]["nome"] == "Anagrafe"
    assert result.transport.requests == 2
    assert result.transport.bytes == 512


def test_web_connector_reports_missing_source_without_fetching() -> None:
    result = WebScrapeConnector().retrieve_live(_request(), mappa=_mappa(sito=None), engine=_Engine())

    assert result.status.value == "not_found"
    assert result.records == ()
