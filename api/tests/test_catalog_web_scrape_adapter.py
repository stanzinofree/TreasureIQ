from datetime import datetime, timezone

from treasureiq.catalog import AccessMode, DataRequest, FreshnessPolicy, Surface, WebScrapeAdapter
from treasureiq.mappa_connettore import MappaConnettore


def _request() -> DataRequest:
    return DataRequest(
        request_id="req-scrape",
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        capability="offices",
        freshness=FreshnessPolicy(max_age_seconds=3600),
        manifest_revision=1,
    )


def _mappa() -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito="https://comune.example",
        sondato_il=datetime.now(timezone.utc).isoformat(),
    )


def test_web_scrape_adapter_returns_the_same_batch_contract() -> None:
    batch = WebScrapeAdapter().read(
        _request(),
        mappa=_mappa(),
        esito=None,
        records=({"nome": "Anagrafe", "url": "https://comune.example/anagrafe"},),
    )

    assert batch.access_mode is AccessMode.INDIRECT
    assert batch.status.value == "fulfilled"
    assert batch.evidence[0].evidence_id.endswith("/anagrafe")
    assert batch.connector.name == "web_scrape"


def test_web_scrape_adapter_reports_empty_without_scrape_output() -> None:
    batch = WebScrapeAdapter().read(_request(), mappa=_mappa(), esito=None)

    assert batch.access_mode is AccessMode.INDIRECT
    assert batch.status.value == "empty"
