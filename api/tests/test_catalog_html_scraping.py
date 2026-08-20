from datetime import datetime, timezone

from treasureiq.catalog import DataRequest, FreshnessPolicy, HtmlScrapeEngine, Surface


def _request() -> DataRequest:
    return DataRequest(
        request_id="req-html",
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        capability="offices",
        freshness=FreshnessPolicy(max_age_seconds=3600),
        manifest_revision=1,
    )


def test_html_engine_extracts_same_host_capability_links(monkeypatch) -> None:
    monkeypatch.setattr(
        "treasureiq.catalog.scraping.fetch_guardato",
        lambda *args, **kwargs: (
            {"content-type": "text/html"},
            b'<a href="/uffici/anagrafe">Anagrafe</a><a href="https://other.example/x">Fuori</a>',
            "https://comune.example/",
        ),
    )

    result = HtmlScrapeEngine().retrieve(source_url="https://comune.example", request=_request())

    assert result.records == ({"nome": "Anagrafe", "url": "https://comune.example/uffici/anagrafe"},)
    assert result.evidence[0].field == "url"


def test_html_engine_returns_empty_for_unmatched_capability(monkeypatch) -> None:
    monkeypatch.setattr(
        "treasureiq.catalog.scraping.fetch_guardato",
        lambda *args, **kwargs: (
            {"content-type": "text/html"},
            b'<a href="/news">Notizia</a>',
            "https://comune.example/",
        ),
    )

    result = HtmlScrapeEngine().retrieve(source_url="https://comune.example", request=_request())

    assert result.records == ()
