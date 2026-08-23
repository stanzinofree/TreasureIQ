from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessMode,
    ConnectorRef,
    ConnectorResult,
    DataStatus,
    EvidenceRef,
    Freshness,
    FreshnessStatus,
    TransportMeta,
)


def test_connector_result_is_transport_neutral() -> None:
    result = ConnectorResult(
        request_id="req-1",
        source_id="058003",
        status=DataStatus.FULFILLED,
        access_mode=AccessMode.INDIRECT,
        records=({"nome": "Anagrafe"},),
        evidence=(EvidenceRef(evidence_id="https://comune.example/anagrafe", field="url"),),
        freshness=Freshness(status=FreshnessStatus.LIVE),
        transport=TransportMeta(requests=1),
        connector=ConnectorRef(name="web_scrape", version="1"),
        retrieved_at=datetime.now(timezone.utc),
    )

    assert result.connector.name == "web_scrape"
    assert result.access_mode is AccessMode.INDIRECT
