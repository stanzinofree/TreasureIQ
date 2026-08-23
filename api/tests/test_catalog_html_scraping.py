from datetime import datetime, timezone

from treasureiq.catalog import DataRequest, FreshnessPolicy, HtmlScrapeEngine, Surface
from treasureiq.extract.pdf_inspection import InspectionRoute, PdfInspection, PdfType
from treasureiq.extract.pdf_engine import PdfExtractionResult


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


def test_html_engine_inspects_transparency_pdf_before_returning_record(monkeypatch) -> None:
    request = _request().model_copy(
        update={"surface": Surface.TRANSPARENCY, "capability": "transparency"}
    )
    pdf_result = PdfExtractionResult(
        inspection=PdfInspection(
            pdf_type=PdfType.TEXT_BASED,
            confidence=0.99,
            page_count=1,
            route=InspectionRoute.NATIVE_TEXT,
        ),
        markdown="# Trasparenza",
    )

    class _PdfEngine:
        def process(self, document_id: str, data: bytes) -> PdfExtractionResult:
            assert document_id.endswith(".pdf")
            assert data == b"pdf"
            return pdf_result

    def fetch(url: str, **kwargs):
        if url.endswith(".pdf"):
            return {"content-type": "application/pdf"}, b"pdf", url
        return {"content-type": "text/html"}, b'<a href="/trasparenza.pdf">Trasparenza PDF</a>', url

    monkeypatch.setattr("treasureiq.catalog.scraping.fetch_guardato", fetch)
    result = HtmlScrapeEngine(pdf_engine=_PdfEngine()).retrieve(
        source_url="https://comune.example", request=request
    )

    assert result.records[0]["pdf_route"] == "native_text"
    assert result.records[0]["markdown"] == "# Trasparenza"


def test_html_engine_reuses_homepage_within_one_run(monkeypatch) -> None:
    calls = 0

    def fetch(url: str, **kwargs):
        nonlocal calls
        calls += 1
        return {"content-type": "text/html"}, b'<a href="/uffici/anagrafe">Anagrafe</a>', url

    monkeypatch.setattr("treasureiq.catalog.scraping.fetch_guardato", fetch)
    engine = HtmlScrapeEngine()

    first = engine.retrieve(source_url="https://comune.example", request=_request())
    second = engine.retrieve(source_url="https://comune.example", request=_request())

    assert calls == 1
    assert first.from_cache is False
    assert second.from_cache is True
