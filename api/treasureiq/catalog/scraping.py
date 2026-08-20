"""Universal acquisition seam for HTML and PDF scraping."""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

from treasureiq.catalog.data_contracts import DataRequest, EvidenceRef, _StrictModel
from treasureiq.ingest.host_guard import fetch_guardato


class ScrapeResult(_StrictModel):
    records: tuple[dict[str, Any], ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    retrieved_at: datetime | None = None
    requests: int = 0
    bytes: int = 0
    limitations: tuple[str, ...] = ()


class ScrapeEngine(Protocol):
    """Engine implemented by HTML/PDF fetch and extraction backends."""

    def retrieve(self, *, source_url: str, request: DataRequest) -> ScrapeResult:
        """Fetch and extract one source request without interpreting chat."""


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        label = " ".join("".join(self._text).split())
        if label and self._href:
            self.links.append((label, self._href))
        self._href = None
        self._text = []


class HtmlScrapeEngine:
    """Small deterministic HTML engine using the project's SSRF guard."""

    _KEYWORDS = {
        "services": ("servizi", "service"),
        "offices": ("uffici", "anagrafe", "sportello"),
        "contacts": ("contatti", "recapiti", "telefono"),
        "transparency": ("trasparenza", "amministrazione-trasparente", "albo"),
    }

    def __init__(self, *, timeout: float = 8.0, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes

    def retrieve(self, *, source_url: str, request: DataRequest) -> ScrapeResult:
        risposta = fetch_guardato(
            source_url,
            timeout=self.timeout,
            max_bytes=self.max_bytes,
            host_atteso=urlparse(source_url).hostname,
        )
        if risposta is None:
            return ScrapeResult(limitations=("La fonte web non ha risposto a una lettura guardata.",))
        headers, payload, final_url = risposta
        content_type = headers.get("content-type", "").lower()
        if "html" not in content_type and not payload.lstrip().startswith((b"<!", b"<html", b"<HTML")):
            return ScrapeResult(
                requests=1,
                bytes=len(payload),
                limitations=("La fonte non ha restituito HTML; il ramo PDF sarà gestito dal PDF engine.",),
            )
        parser = _LinkParser()
        parser.feed(payload.decode("utf-8", errors="replace"))
        keywords = self._KEYWORDS.get(request.capability, ())
        base_host = (urlparse(final_url).hostname or "").lower()
        records: list[dict[str, Any]] = []
        evidence: list[EvidenceRef] = []
        for label, href in parser.links:
            url = urljoin(final_url, href)
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != base_host:
                continue
            haystack = f"{label} {parsed.path}".lower()
            if not any(keyword in haystack for keyword in keywords):
                continue
            if any(record["url"] == url for record in records):
                continue
            records.append({"nome": label, "url": url})
            evidence.append(EvidenceRef(evidence_id=url, field="url"))
        return ScrapeResult(
            records=tuple(records[: request.limits.max_records]),
            evidence=tuple(evidence[: request.limits.max_records]),
            requests=1,
            bytes=len(payload),
            limitations=("I record sono link pubblicati nella pagina HTML della fonte.",),
        )
