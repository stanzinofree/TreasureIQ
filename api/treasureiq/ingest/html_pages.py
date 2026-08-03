"""Generic HTML connector for institutional sites with no public API (D-22).

Ariccia (`comune.ariccia.rm.it`) and Genzano di Roma (`comune.genzanodiroma
.roma.it`) both returned 404/410 on `/wp-json` and publish nothing on
dati.gov.it (`.kapi/spec.md` amendments round 2, F-3). Their content is
still server-side HTML, so a bespoke scraper can reach it — at a cost that
`wp_rest`/`wp_pages` never pay, because those sites expose typed JSON.

Two constraints shape this module, both non-negotiable (D-22/D-23):

1. **No headless browser.** Only what the server actually sends over the
   wire, parsed with stdlib `html.parser` — no new dependency, no rendering.
   A site whose content only exists after client-side JavaScript runs (e.g.
   `aricicla.com`, a Wix SPA — F-3) is unreachable by design, and that is a
   measured finding, not a bug to route around.
2. **`aricicla.com` is never fetched, parsed or ingested.** It is a private
   third-party domain; TreasureIQ links it for the citizen to verify
   themselves, and does not scrape it (D-23). `FORBIDDEN_DOMAINS` below is
   checked against every candidate link before it is ever queued, not just
   against the two configured base URLs.

Extraction is NOT reimplemented here. Every candidate page's body text runs
through the exact same `extract.llm.RequirementsExtractor` that
`wp_pages.WPPagesConnector` uses, reusing its `_ELIGIBILITY_SIGNAL_RE`
content filter, its `MAX_CORPUS_CHARS` budget and its
`_count_recovered_fields` accounting — so D-05's quote gate applies
identically: a selector that drifts, or a page whose template changed,
yields nothing, never a plausible fabrication (R-11).

This connector's own build cost — lines of code, HTML selectors, pages
fetched, wall-clock seconds — is `data/enti.json`'s M4 evidence per D-21: as
much the deliverable here as any record it recovers.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from treasureiq.extract.llm import RequirementsExtractor, Segment
from treasureiq.ingest.base import Connector
from treasureiq.ingest.wp_comuni import guess_kind, strip_html
from treasureiq.ingest.wp_pages import (
    _ELIGIBILITY_SIGNAL_RE,
    MAX_CORPUS_CHARS,
    _count_recovered_fields,
)
from treasureiq.schema import (
    Confidence,
    Opportunity,
    RecoveryLevel,
    Requirements,
    Source,
    TargetGroup,
)

logger = logging.getLogger(__name__)

#: D-23 — checked against every resolved link's netloc, not just the two
#: configured base URLs, so a candidate discovered mid-crawl cannot slip
#: through. `aricicla.com` is described and linked for the citizen, never
#: fetched.
FORBIDDEN_DOMAINS = ("aricicla.com",)

_SKIP_EXT_RE = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|css|js|zip|docx?|xlsx?|ics)$", re.IGNORECASE
)
_SKIP_SCHEME_RE = re.compile(r"^(mailto|tel|javascript):", re.IGNORECASE)

#: Generic civic-info signal, broader than wp_pages' eligibility-only filter
#: (isee/reddito/beneficiari): most of what a citizen asks an institutional
#: site — collection days, office hours, an address — carries no eligibility
#: language at all. Used *alongside* the imported `_ELIGIBILITY_SIGNAL_RE`,
#: never instead of it, so a page that does state eligibility criteria is
#: still caught by the same signal `wp_pages.py` was measured against.
_INFO_SIGNAL_RE = re.compile(
    r"orari|ufficio|raccolta|rifiut|vetro|calendari|anagraf|residen|"
    r"certificat|urp|contribut|servizio|regolament",
    re.IGNORECASE,
)

#: Below this, a "candidate" page is a stub/redirect/placeholder — not worth
#: the extraction cost, and not worth reporting as a recovered record.
MIN_BODY_CHARS = 200


class _LinkAndTextParser(HTMLParser):
    """Collects same-page `<a href>` links and best-effort main-content text.

    Two selectors, and they are the entire "bespoke" part of this connector
    (D-21 asks for the selector count to be counted, not just claimed):
    1. any `<a href>` — for candidate discovery on listing pages.
    2. `<main>`/`<article>` as the content landmark, when the template
       provides one; falls back to the full page otherwise, because a
       missing landmark must degrade to "everything", never to "nothing".
    `<script>`/`<style>`/`<nav>`/`<header>`/`<footer>` are always excluded
    from body text, landmark or not — boilerplate is not a citizen's answer.
    """

    _CONTENT_TAGS = {"main", "article"}
    _SKIP_TAGS = {"script", "style", "nav", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._link_href: str | None = None
        self._link_text_parts: list[str] = []
        self._content_depth = 0
        self._skip_depth = 0
        self._saw_content_landmark = False
        self._content_parts: list[str] = []
        self._fallback_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in self._CONTENT_TAGS:
            self._content_depth += 1
            self._saw_content_landmark = True
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "a" and attrs_dict.get("href"):
            self._link_href = attrs_dict["href"]
            self._link_text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self._CONTENT_TAGS and self._content_depth > 0:
            self._content_depth -= 1
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "a" and self._link_href is not None:
            text = " ".join("".join(self._link_text_parts).split())
            self.links.append((self._link_href, text))
            self._link_href = None
            self._link_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._link_href is not None:
            self._link_text_parts.append(data)
        if self._skip_depth > 0:
            return
        if self._content_depth > 0:
            self._content_parts.append(data)
        else:
            self._fallback_parts.append(data)

    @property
    def text(self) -> str:
        parts = self._content_parts if self._saw_content_landmark else self._fallback_parts
        return " ".join("".join(parts).split())


class HTMLPagesConnector(Connector):
    """Best-effort connector for a comune's institutional site, no API.

    Analog of `wp_pages.WPPagesConnector`: same `Connector` base, same
    quote-gated extraction leg, same D-16/D-17 recovery-cost instrumentation
    on every emitted record. What differs is candidate discovery — there is
    no `/wp-json` search endpoint here, so candidates come from crawling the
    configured `listing_paths` for same-domain links instead.

    Never sets `Requirements.source_typed` (`schema.py`): nothing this
    connector reads is a declared typed field, everything is inference from
    prose, exactly like `wp_pages.py`.
    """

    name = "html_scrape"
    #: Lower than wp_pages (0.4): no typed API of any kind, best-effort
    #: scraping of a template this project does not control and did not
    #: choose (D-21's "alto" access-mode label, earned rather than asserted).
    transport_quality = 0.2

    def __init__(
        self,
        *,
        base_url: str,
        ente: str,
        codice_istat: str,
        listing_paths: tuple[str, ...],
        extractor: RequirementsExtractor | None = None,
        timeout: float = 30.0,
        max_pages: int = 10,
    ) -> None:
        super().__init__(timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.ente = ente
        self.codice_istat = codice_istat
        self.listing_paths = listing_paths
        self.stats.source_id = f"{self.name}:{codice_istat}"
        self._extractor = extractor
        self.max_pages = max_pages
        #: Audit trail of candidates dropped before or after fetch, mirroring
        #: `wp_pages.WPPagesConnector.dropped` for `--verbose` reporting.
        self.dropped: list[str] = []
        #: D-21 evidence: measured, not estimated. Read back by
        #: `ingest/__main__.py` into `data/enti.json`'s M4 block.
        self.pages_fetched = 0
        self.fetch_seconds = 0.0

    def fetch(self) -> list[Opportunity]:
        started = time.perf_counter()
        try:
            candidates = self._collect_candidate_links()
            selected = self._select_pages(candidates)

            opportunities: list[Opportunity] = []
            for url, anchor_text in selected:
                self.stats.records_seen += 1
                try:
                    opportunity = self._fetch_and_normalise(url, anchor_text)
                except Exception as exc:  # one bad page must not kill the run
                    msg = f"page {url}: {exc}"
                    logger.warning("normalisation failed for %s", msg)
                    self.stats.errors.append(msg)
                    continue
                if opportunity is None:
                    continue
                opportunities.append(opportunity)
                self.stats.records_emitted += 1
                if not opportunity.requirements.is_empty:
                    self.stats.with_extracted_requirements += 1
            return opportunities
        finally:
            self.fetch_seconds = time.perf_counter() - started

    def _get_html(self, path_or_url: str) -> str:
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else f"{self.base_url}{path_or_url}"
        )
        resp = self._client.get(url)
        resp.raise_for_status()
        self.pages_fetched += 1
        return resp.text

    def _collect_candidate_links(self) -> dict[str, str]:
        """Same-domain links found on the configured listing pages, deduped by URL."""
        found: dict[str, str] = {}
        base_netloc = urlsplit(self.base_url).netloc
        for path in self.listing_paths:
            try:
                html_text = self._get_html(path)
            except Exception as exc:
                logger.warning("listing page %s unreachable: %s", path, exc)
                self.stats.errors.append(f"listing {path} unreachable: {exc}")
                continue
            parser = _LinkAndTextParser()
            parser.feed(html_text)
            page_url = f"{self.base_url}{path}"
            for href, text in parser.links:
                if _SKIP_SCHEME_RE.match(href):
                    continue
                absolute = urljoin(page_url, href)
                netloc = urlsplit(absolute).netloc
                if any(domain in netloc for domain in FORBIDDEN_DOMAINS):
                    # D-23: never queued, never fetched, not even counted.
                    continue
                if netloc and netloc != base_netloc:
                    continue
                if _SKIP_EXT_RE.search(urlsplit(absolute).path):
                    continue
                if absolute not in found and absolute not in (page_url, self.base_url + "/"):
                    found[absolute] = text
        return found

    def _select_pages(self, candidates: dict[str, str]) -> list[tuple[str, str]]:
        """Rank by anchor-text relevance, cap fetches to `max_pages`.

        Small municipal servers, not a CDN: bounding the fetch count before
        a single page GET happens is the "good citizen" half of D-22, the
        content filter in `_fetch_and_normalise` is the other half.
        """

        def relevance(item: tuple[str, str]) -> int:
            _, text = item
            if _ELIGIBILITY_SIGNAL_RE.search(text) or _INFO_SIGNAL_RE.search(text):
                return 1
            return 0

        ranked = sorted(candidates.items(), key=relevance, reverse=True)
        selected = ranked[: self.max_pages]
        for url, _ in ranked[self.max_pages :]:
            self.dropped.append(f"{url}: oltre il limite di {self.max_pages} pagine candidate")
        return selected

    def _fetch_and_normalise(self, url: str, anchor_text: str) -> Opportunity | None:
        try:
            html_text = self._get_html(url)
        except Exception as exc:
            self.dropped.append(f"{url}: pagina non raggiungibile ({exc})")
            return None

        parser = _LinkAndTextParser()
        parser.feed(html_text)
        body_text = parser.text or strip_html(html_text)

        if len(body_text) < MIN_BODY_CHARS:
            self.dropped.append(f"{url}: corpo troppo corto ({len(body_text)} caratteri)")
            return None

        title = anchor_text.strip() or url

        # D-16: wall-clock cost of recovering this record's criteria.
        recovery_started = time.perf_counter()

        full_segment = Segment(kind="pagina", url=url, page_number=None, start=0, text=body_text)
        corpus = body_text
        visible_len = len(corpus)
        if len(corpus) > MAX_CORPUS_CHARS:
            corpus = corpus[:MAX_CORPUS_CHARS]
            visible_len = MAX_CORPUS_CHARS
        visible_segment = Segment(
            kind="pagina", url=url, page_number=None, start=0, text=body_text[:visible_len]
        )

        requirements = Requirements()
        notes: list[str] = []
        confidence = Confidence.INFERRED
        chars_processed: int | None = None
        requirements_recovered: int | None = None
        raw_hash = hashlib.sha256(f"{url}:{body_text}".encode()).hexdigest()[:16]

        if self._extractor is not None and self._extractor.available:
            chars_processed = len(corpus)
            outcome = self._extractor.extract(
                text=corpus,
                title=title,
                raw_hash=raw_hash,
                visible_segments=[visible_segment],
                full_segments=[full_segment],
            )
            if outcome is not None:
                requirements, extraction_notes, confidence = outcome
                notes.extend(extraction_notes)
                requirements_recovered = _count_recovered_fields(requirements)
            else:
                notes.append(
                    "Estrazione non eseguita (nessuna cache disponibile e "
                    "provider non disponibile in questo momento)."
                )
        else:
            notes.append(
                "Estrazione LLM non eseguita: nessun provider disponibile in questo ambiente."
            )

        extraction_seconds = time.perf_counter() - recovery_started

        # D-16 ladder: no PDFs on this leg (scope cut, see html_pages.py
        # module docstring / brief return notes) — L2 whenever something
        # quote-gated survived, L1 otherwise. L3 (illegible attachment)
        # does not apply: this connector never opens attachments.
        recovery_level = (
            RecoveryLevel.L2_ESTRATTO
            if requirements_recovered is not None and requirements_recovered >= 1
            else RecoveryLevel.L1_MANUALE
        )

        # NEVER set Requirements.source_typed here — nothing read by this
        # connector is a declared typed field (module docstring).
        source = Source(
            ente=self.ente,
            ente_codice_istat=self.codice_istat,
            connector=self.name,
            url=url,
            api_url=None,
            fetched_at=self.now(),
            raw_hash=raw_hash,
        )

        return Opportunity(
            id=f"{self.name}:{self.codice_istat}:{raw_hash}",
            kind=guess_kind(title, body_text),
            targets=[TargetGroup.TUTTI],
            title=title,
            summary=body_text[:400] or None,
            body=body_text or None,
            requirements=requirements,
            source=source,
            confidence=confidence,
            extraction_notes=notes,
            recovery_level=recovery_level,
            pdfs_linked=0,
            pdfs_opened=0,
            pdfs_skipped=[],
            chars_processed=chars_processed,
            extraction_seconds=extraction_seconds,
            requirements_recovered=requirements_recovered,
        )
