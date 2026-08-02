"""Ingestion connector for Albano's plain WordPress `pages`.

Bandi, concorsi and volontariato notices at Albano do not live in the typed
`servizi` post type — they live as ordinary WP `pages`: prose HTML, zero
CMB2 metaboxes (`.kapi/spec.md` D-03). This connector cannot declare
eligibility the way `WPComuniConnector` does from typed fields; every
requirement it emits, if any, comes from the quote-gated LLM extractor
(`extract.llm.RequirementsExtractor`) reading the page body and, when
present, its linked PDF attachments (D-15).

Candidate selection is two-staged (`.kapi/spike-d07.md` addendum):
1. the six keyword searches measured in the spike, deduped by WP page id;
2. a content filter — keep a page only if its body carries an eligibility
   signal or it links at least one PDF. Unfiltered, the six keywords return
   mostly unrelated municipal pages (statistica, PagoPA, raccolta
   differenziata...); the spike measured this directly. Every drop is
   logged with its reason so the selection is auditable, not silent.

A page whose body and attachments state nothing extractable still becomes a
record — with `requirements.is_empty` True and `Confidence.INFERRED` — an
empty requirements set is itself the finding: "the comune published this and
said nothing checkable."

This connector never sets `Requirements.source_typed`. Pages carry no typed
CMB2 field whatsoever; `source_typed` is a provenance guard (`schema.py:169`)
attesting that a genuinely typed field was read, not a convenience flag —
setting it here would be a false provenance claim.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime
from typing import Any

from treasureiq.extract.llm import RequirementsExtractor
from treasureiq.ingest.base import Connector
from treasureiq.ingest.wp_comuni import guess_kind, strip_html
from treasureiq.schema import (
    Confidence,
    Opportunity,
    Requirements,
    Source,
    TargetGroup,
)

logger = logging.getLogger(__name__)

#: The six keyword searches measured in the spike (D-07/D-15) — kept
#: identical so a live B4 run sees exactly the corpus that was measured in
#: `.kapi/spike-d07.md`, not a superset or subset of it.
SEARCH_KEYWORDS = (
    "bando",
    "avviso pubblico",
    "concorso",
    "volontariato",
    "contributo",
    "borsa",
)

#: Post-spike control measurement (`.kapi/spike-d07.md` addendum): a page is
#: worth extracting from only if its body carries one of these signals, or it
#: links PDF attachments (where the spike found the real criteria living).
_ELIGIBILITY_SIGNAL_RE = re.compile(
    r"isee|requisit|destinatar|possono presentare|possono partecipare|"
    r"aventi diritto|beneficiar|residenz|anni di età|reddito",
    re.IGNORECASE,
)

_PDF_LINK_RE = re.compile(r'href="([^"]+?\.pdf)"', re.IGNORECASE)

#: D-15 budget knobs — hard caps that keep a full run in minutes, not hours.
MAX_PDFS_PER_PAGE = 5
MAX_PDF_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_CORPUS_CHARS = 12_000

#: Filenames far more likely to carry eligibility criteria than
#: administrative boilerplate (D-15) — a preference order, not an exclusion:
#: a deprioritised PDF is still opened if the per-page slot allows it.
_PREFERRED_FILENAME_RE = re.compile(r"bando|avviso|regolament", re.IGNORECASE)
_DEPRIORITISED_FILENAME_RE = re.compile(r"modulo|domanda|allegat", re.IGNORECASE)


def _filename_rank(url: str) -> int:
    """Lower sorts first: preferred filenames before neutral before deprioritised."""
    if _PREFERRED_FILENAME_RE.search(url):
        return 0
    if _DEPRIORITISED_FILENAME_RE.search(url):
        return 2
    return 1


class WPPagesConnector(Connector):
    """Ingests bandi/concorsi/volontariato notices from Albano's WP `pages`.

    Unlike `WPComuniConnector`, there is no typed field to trust: every
    candidate page is prose HTML, filtered by the eligibility-signal /
    PDF-presence heuristic above, then handed to the quote-gated LLM
    extractor (`RequirementsExtractor`). Fail-soft throughout: one bad page,
    one bad keyword search, or one unreadable PDF must not take the run down.
    """

    name = "wp_pages"
    #: Prose HTML with no typed fields — lower baseline trust than `wp_rest`
    #: (0.8), reflecting that everything here is inference, never declaration.
    transport_quality = 0.4

    def __init__(
        self,
        *,
        base_url: str,
        ente: str,
        codice_istat: str,
        extractor: RequirementsExtractor | None = None,
        timeout: float = 30.0,
        max_pages: int = 50,
    ) -> None:
        super().__init__(timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.ente = ente
        self.codice_istat = codice_istat
        self.stats.source_id = f"{self.name}:{codice_istat}"
        self._extractor = extractor
        self.max_pages = max_pages
        #: Audit trail of pages the content filter dropped, and why. Not part
        #: of `FetchStats` because these are pre-filter exclusions, not
        #: post-fetch errors — but still worth reporting to whoever runs the
        #: CLI with `--verbose`.
        self.dropped: list[str] = []

    @property
    def api_root(self) -> str:
        return f"{self.base_url}/wp-json/wp/v2"

    def fetch(self) -> list[Opportunity]:
        candidates = self._search_candidate_pages()
        selected = self._select_pages(candidates)

        opportunities: list[Opportunity] = []
        for record in selected:
            self.stats.records_seen += 1
            try:
                opportunity = self._normalise(record)
            except Exception as exc:  # one bad page must not kill the run
                msg = f"page id={record.get('id')}: {exc}"
                logger.warning("normalisation failed for %s", msg)
                self.stats.errors.append(msg)
                continue
            opportunities.append(opportunity)
            self.stats.records_emitted += 1
            if not opportunity.requirements.is_empty:
                self.stats.with_extracted_requirements += 1
            if opportunity.deadline:
                self.stats.with_deadline += 1
        return opportunities

    def _search_candidate_pages(self) -> list[dict[str, Any]]:
        """The six keyword searches over `pages`, deduped by WP page id.

        Mirrors `extract/spike.py`'s `fetch_candidate_pages` so this
        connector's corpus matches what `.kapi/spike-d07.md` measured.
        """
        seen: dict[int, dict[str, Any]] = {}
        for keyword in SEARCH_KEYWORDS:
            if len(seen) >= self.max_pages:
                break
            try:
                payload, _headers = self._get_json(
                    f"{self.api_root}/pages", search=keyword, per_page=20
                )
            except Exception as exc:
                logger.warning("page search %r failed: %s", keyword, exc)
                self.stats.errors.append(f"search {keyword!r} failed: {exc}")
                continue
            if not isinstance(payload, list):
                logger.warning("page search %r: unexpected payload shape", keyword)
                self.stats.errors.append(
                    f"search {keyword!r}: unexpected payload shape"
                )
                continue
            for record in payload:
                page_id = record.get("id")
                if page_id is None or page_id in seen:
                    continue
                seen[page_id] = record
        return list(seen.values())[: self.max_pages]

    def _select_pages(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep a page only if it carries an eligibility signal or links a PDF.

        The six keywords alone return mostly unrelated municipal pages
        (measured in `.kapi/spike-d07.md`); this is the content filter the
        spike's addendum found necessary. Every drop is logged with its
        reason, at INFO so `--verbose` surfaces the full selection audit.
        """
        selected: list[dict[str, Any]] = []
        for record in candidates:
            title = strip_html(
                record.get("title", {}).get("rendered", "")
            ).strip() or f"page {record.get('id')}"
            body_html = record.get("content", {}).get("rendered", "")
            body_text = strip_html(body_html)
            has_signal = bool(_ELIGIBILITY_SIGNAL_RE.search(body_text))
            pdf_links = _PDF_LINK_RE.findall(body_html)

            if has_signal or pdf_links:
                selected.append(record)
                continue

            reason = "nessun segnale di ammissibilità nel corpo, nessun PDF collegato"
            logger.info(
                "dropping page id=%s %r: %s", record.get("id"), title[:60], reason
            )
            self.dropped.append(f"{record.get('id')} {title[:60]!r}: {reason}")
        return selected

    def _normalise(self, record: dict[str, Any]) -> Opportunity:
        page_id = record.get("id")
        title = strip_html(
            record.get("title", {}).get("rendered", "")
        ).strip() or f"page {page_id}"
        body_html = record.get("content", {}).get("rendered", "")
        body_text = strip_html(body_html)
        page_url = record.get("link") or self.base_url

        pdf_urls = _PDF_LINK_RE.findall(body_html)
        pdf_segments, pdf_notes = self._collect_pdf_segments(pdf_urls)

        # Body first, so a body-only match is attributed to the page itself
        # before any PDF segment is even considered.
        segments: list[dict[str, Any]] = [
            {"kind": "pagina", "url": page_url, "pages": [body_text]}
        ]
        segments.extend(pdf_segments)

        corpus = body_text
        for seg in pdf_segments:
            corpus = f"{corpus}\n\n# Allegato: {seg['url']}\n" + "\n".join(seg["pages"])
        if len(corpus) > MAX_CORPUS_CHARS:
            corpus = corpus[:MAX_CORPUS_CHARS]

        requirements = Requirements()
        notes: list[str] = list(pdf_notes)
        confidence = Confidence.INFERRED

        if self._extractor is not None and self._extractor.available:
            raw_hash = self.hash_payload(record)
            outcome = self._extractor.extract(
                text=corpus, title=title, raw_hash=raw_hash
            )
            if outcome is not None:
                requirements, extraction_notes, confidence = outcome
                notes.extend(extraction_notes)
                notes.extend(self._attribute_quotes(raw_hash, segments))
            else:
                notes.append(
                    "Estrazione non eseguita (nessuna cache disponibile e "
                    "provider non disponibile in questo momento)."
                )
        else:
            notes.append(
                "Estrazione LLM non eseguita: nessun provider disponibile "
                "in questo ambiente."
            )

        # NEVER set Requirements.source_typed here — see module docstring.

        source = Source(
            ente=self.ente,
            ente_codice_istat=self.codice_istat,
            connector=self.name,
            url=page_url,
            api_url=f"{self.api_root}/pages/{page_id}",
            fetched_at=self.now(),
            raw_hash=self.hash_payload(record),
        )

        opens_at: date | None = None
        raw_date = record.get("date")
        if isinstance(raw_date, str) and raw_date:
            try:
                opens_at = datetime.fromisoformat(raw_date).date()
            except ValueError:
                notes.append(f"Data di pubblicazione non interpretabile: {raw_date}")

        return Opportunity(
            id=f"{self.name}:{self.codice_istat}:{page_id}",
            kind=guess_kind(title, body_text),
            targets=[TargetGroup.TUTTI],
            title=title,
            summary=body_text[:400] or None,
            body=body_text or None,
            requirements=requirements,
            opens_at=opens_at,
            source=source,
            confidence=confidence,
            extraction_notes=notes,
        )

    def _collect_pdf_segments(
        self, pdf_urls: list[str]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Download and extract text from up to `MAX_PDFS_PER_PAGE` attachments.

        `pypdf` is imported lazily (only pages that actually link a PDF pay
        this cost, matching `extract/llm.py`'s lazy-import convention for
        `anthropic`). Every skip — cap reached, too large, download failure,
        unreadable — is logged and returned as a human-readable note, per
        D-15: "log every skip explicitly."
        """
        notes: list[str] = []
        if not pdf_urls:
            return [], notes

        ranked = sorted(dict.fromkeys(pdf_urls), key=_filename_rank)

        segments: list[dict[str, Any]] = []
        opened = 0
        for url in ranked:
            absolute_url = url if url.startswith("http") else f"{self.base_url}{url}"

            if opened >= MAX_PDFS_PER_PAGE:
                reason = f"limite di {MAX_PDFS_PER_PAGE} allegati per pagina raggiunto"
                logger.info("skipping PDF %s: %s", absolute_url, reason)
                notes.append(f"Allegato PDF ignorato ({reason}): {absolute_url}")
                continue

            content_length = 0
            try:
                head = self._client.head(absolute_url)
                content_length = int(head.headers.get("content-length", 0) or 0)
            except Exception:
                content_length = 0  # HEAD unsupported/failed — fall through to GET

            if content_length and content_length > MAX_PDF_BYTES:
                reason = f"{content_length} byte, oltre il limite di {MAX_PDF_BYTES} byte"
                logger.info("skipping PDF %s: %s", absolute_url, reason)
                notes.append(f"Allegato PDF ignorato (troppo grande, {reason}): {absolute_url}")
                continue

            try:
                response = self._client.get(absolute_url)
                response.raise_for_status()
            except Exception as exc:
                logger.info("skipping PDF %s: download failed: %s", absolute_url, exc)
                notes.append(f"Allegato PDF non scaricabile: {absolute_url} ({exc})")
                continue

            if len(response.content) > MAX_PDF_BYTES:
                reason = f"{len(response.content)} byte, oltre il limite di {MAX_PDF_BYTES} byte"
                logger.info("skipping PDF %s: %s", absolute_url, reason)
                notes.append(f"Allegato PDF ignorato (troppo grande, {reason}): {absolute_url}")
                continue

            try:
                import pypdf  # lazy: only pages with a linked PDF pay this cost

                reader = pypdf.PdfReader(io.BytesIO(response.content))
                pages_text = [(p.extract_text() or "") for p in reader.pages]
            except Exception as exc:
                logger.info("skipping PDF %s: parse failed: %s", absolute_url, exc)
                notes.append(f"Allegato PDF illeggibile (parsing fallito): {absolute_url} ({exc})")
                continue

            if not any(t.strip() for t in pages_text):
                reason = "nessun testo estraibile (probabile scansione/immagine)"
                logger.info("skipping PDF %s: %s", absolute_url, reason)
                notes.append(f"Allegato PDF ignorato ({reason}): {absolute_url}")
                continue

            opened += 1
            segments.append({"kind": "allegato", "url": absolute_url, "pages": pages_text})

        return segments, notes

    def _attribute_quotes(
        self, raw_hash: str, segments: list[dict[str, Any]]
    ) -> list[str]:
        """Cite each accepted quote back to the page or the PDF it came from.

        D-05 applied at the attachment level: a quote drawn from an
        attachment must cite the attachment (URL, and page number when
        `pypdf` provides one), never be flattened onto the page URL. Reads
        the raw model output back from the extractor's on-disk cache (the
        same technique `extract/spike.py` uses for gate inspection) because
        `RequirementsExtractor.extract()` only returns the post-gate
        `Requirements`, not the quotes that justified them.
        """
        if self._extractor is None:
            return []
        raw = self._extractor.cache.get(raw_hash)
        if raw is None:
            return []

        notes: list[str] = []
        for quote in raw.quotes:
            source_note = None
            for seg in segments:
                for page_index, page_text in enumerate(seg["pages"], start=1):
                    if quote.text and quote.text in page_text:
                        if seg["kind"] == "allegato":
                            source_note = (
                                f"Fonte per '{quote.field}': allegato {seg['url']}"
                                + (
                                    f", pagina {page_index}"
                                    if len(seg["pages"]) > 1
                                    else ""
                                )
                                + f' — "{quote.text}"'
                            )
                        else:
                            source_note = (
                                f"Fonte per '{quote.field}': pagina web {seg['url']}"
                                f' — "{quote.text}"'
                            )
                        break
                if source_note:
                    break
            if source_note is None:
                # Should be rare under D-05 (quotes are meant to be verbatim),
                # but a paraphrase or truncation could slip through — log it
                # rather than guess a source.
                source_note = (
                    f"Fonte per '{quote.field}' non identificata con precisione "
                    f'nel corpus assemblato — "{quote.text}"'
                )
            notes.append(source_note)
        return notes
