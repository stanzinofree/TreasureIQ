from types import SimpleNamespace

import httpx

import treasureiq.extract.corpus as corpus
from treasureiq.extract.pdf_inspection import InspectionRoute, PdfInspection, PdfType


class _Client:
    def head(self, _url: str):
        return httpx.Response(200, headers={"content-length": "3"})

    def get(self, url: str):
        return httpx.Response(
            200,
            content=b"not a real pdf",
            headers={"content-type": "application/pdf"},
            request=httpx.Request("GET", url),
        )


def test_corpus_routes_scanned_pdf_to_ocr_before_pypdf(monkeypatch) -> None:
    inspection = PdfInspection(
        pdf_type=PdfType.SCANNED,
        confidence=0.99,
        page_count=1,
        route=InspectionRoute.FULL_OCR,
    )
    monkeypatch.setattr(corpus, "inspect_pdf_bytes", lambda *_args, **_kwargs: inspection)
    monkeypatch.setitem(__import__("sys").modules, "pypdf", SimpleNamespace())

    segments, notes, skipped, illegible = corpus.collect_pdf_segments(
        _Client(),
        "https://comune.example",
        ["https://comune.example/bando.pdf"],
    )

    assert segments == []
    assert "OCR" in notes[0]
    assert skipped[0].reason == "ispezione PDF: OCR richiesto prima dell'estrazione"
    assert illegible == 1
