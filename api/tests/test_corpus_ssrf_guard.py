"""SSRF TOCTOU guard on `collect_pdf_segments` (D-08 / A5).

The pre-fetch host filter (`_filtra_pdf_stesso_host` in `bandi_live.py`, or
the caller-side check in `api.py`) only looks at the URL STRING before the
request. `httpx.Client(follow_redirects=True)` can still land the response on
a different host — this module must re-check `response.url` AFTER the fetch
and skip anything that lands off-host, never extract it. No network: the
transport is a fake `httpx.MockTransport`.
"""

from __future__ import annotations

import httpx

from treasureiq.extract.corpus import collect_pdf_segments

BASE_URL = "http://comune-corpus-test.example"
HOST_ATTESO = "comune-corpus-test.example"
HOST_ESTERNO = "host-esterno.example.com"


def _transport_rediretto(request: httpx.Request) -> httpx.Response:
    """Ogni richiesta al comune rediretta su un host esterno; l'host esterno
    risponde con contenuto (mai un PDF vero: la guardia deve scartare PRIMA
    di arrivare a `pypdf`)."""
    if request.url.host == HOST_ATTESO:
        return httpx.Response(
            302,
            headers={"location": f"http://{HOST_ESTERNO}/files/pdf-esca.pdf"},
        )
    return httpx.Response(
        200,
        content=b"contenuto arbitrario da host esterno",
        headers={"content-type": "application/pdf"},
    )


def test_pdf_rediretto_fuori_host_e_scartato_toctou():
    client = httpx.Client(
        transport=httpx.MockTransport(_transport_rediretto), follow_redirects=True
    )

    segments, notes, skipped, illegible_count, ocr_deferred_count = collect_pdf_segments(
        client, BASE_URL, ["/files/allegato.pdf"]
    )

    assert segments == []
    assert illegible_count == 0
    assert ocr_deferred_count == 0
    assert len(skipped) == 1
    assert skipped[0].reason == "rediretto fuori host"
    assert any("rediretto fuori host" in nota for nota in notes)
