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

D-16/D-17 recovery-cost instrumentation lives here too: `_normalise` measures
what it actually cost to recover this record's criteria (PDFs linked/opened/
skipped, characters processed, wall-clock seconds, requirements recovered)
and lands the record on one of the three ladder rungs. Instrumentation only —
see `schema.Opportunity`'s docstring on those fields: nothing computed here is
read by `match/engine.py`, and an unmeasured value is `None`, never a guess.
"""

from __future__ import annotations

import io
import logging
import re
import time
from datetime import date, datetime
from typing import Any

from treasureiq.extract.llm import RequirementsExtractor, Segment
from treasureiq.ingest.base import Connector
from treasureiq.ingest.wp_comuni import guess_kind, strip_html
from treasureiq.schema import (
    Confidence,
    Opportunity,
    PdfSkip,
    RecoveryLevel,
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


def _count_recovered_fields(req: Requirements) -> int:
    """D-16: how many quote-gated requirement fields survived into `req`.

    Counts only fields that carry real information beyond the schema's
    defaults — `residenza_required` starts `True` unconditionally, so it only
    counts here when a quote moved it to `False` (the one case that reflects
    an actual extraction, per `extract/llm.py:to_requirements`). This never
    reads quotes directly; it counts the post-gate `Requirements` object that
    `match/engine.py` also consumes, so the count reflects exactly what
    survived D-05's gate, nothing more.
    """
    count = 0
    if req.isee_max is not None:
        count += 1
    if req.isee_min is not None:
        count += 1
    if req.eta_min is not None:
        count += 1
    if req.eta_max is not None:
        count += 1
    if req.nucleo_min is not None:
        count += 1
    if req.figli_minori_required is not None:
        count += 1
    if req.disabilita_required is not None:
        count += 1
    if req.residenza_required is False:
        count += 1
    count += len(req.employment_status)
    count += len(req.other)
    return count


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
        pdf_urls_unique = list(dict.fromkeys(pdf_urls))

        # D-16: wall-clock cost of recovering this record's criteria, from
        # here through the extraction attempt below. Always measured — even a
        # record with no PDFs and an unavailable extractor still pays this
        # cost, and a real (small) number beats a null for a code path that
        # genuinely ran.
        recovery_started = time.perf_counter()

        pdf_segments, pdf_notes, pdf_skipped, pdf_illegible_count = (
            self._collect_pdf_segments(pdf_urls)
        )

        # Assemble the corpus and record each segment's character offset
        # within it *before* truncation, so attribution can later tell which
        # segments (or which tail of a segment) the model actually saw.
        # Body first, so a body-only match is attributed to the page itself
        # before any PDF segment is even considered.
        boundary_segments: list[Segment] = []
        corpus_parts: list[str] = [body_text]
        offset = len(body_text)
        boundary_segments.append(
            Segment(kind="pagina", url=page_url, page_number=None, start=0, text=body_text)
        )
        for seg in pdf_segments:
            header = f"\n\n# Allegato: {seg['url']}\n"
            corpus_parts.append(header)
            offset += len(header)
            for page_index, page_text in enumerate(seg["pages"], start=1):
                if page_index > 1:
                    corpus_parts.append("\n")
                    offset += 1
                boundary_segments.append(
                    Segment(
                        kind="allegato",
                        url=seg["url"],
                        page_number=page_index,
                        start=offset,
                        text=page_text,
                    )
                )
                corpus_parts.append(page_text)
                offset += len(page_text)

        corpus = "".join(corpus_parts)
        visible_len = len(corpus)
        if len(corpus) > MAX_CORPUS_CHARS:
            corpus = corpus[:MAX_CORPUS_CHARS]
            visible_len = MAX_CORPUS_CHARS

        # Segments (or the tail of a segment) beyond `visible_len` were never
        # sent to the model — a quote cannot legitimately be attributed to
        # them, cap or not (D-15's MAX_CORPUS_CHARS).
        visible_segments = [
            Segment(
                kind=seg.kind,
                url=seg.url,
                page_number=seg.page_number,
                start=seg.start,
                text=seg.text[: max(0, visible_len - seg.start)],
            )
            for seg in boundary_segments
            if seg.start < visible_len
        ]

        requirements = Requirements()
        notes: list[str] = list(pdf_notes)
        confidence = Confidence.INFERRED

        # D-16: `None` unless extraction actually ran (cache hit, live call,
        # or an attempted-but-failed live call) — never a guessed zero.
        chars_processed: int | None = None
        requirements_recovered: int | None = None

        if self._extractor is not None and self._extractor.available:
            chars_processed = len(corpus)
            raw_hash = self.hash_payload(record)
            outcome = self._extractor.extract(
                text=corpus,
                title=title,
                raw_hash=raw_hash,
                visible_segments=visible_segments,
                full_segments=boundary_segments,
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
                "Estrazione LLM non eseguita: nessun provider disponibile "
                "in questo ambiente."
            )

        extraction_seconds = time.perf_counter() - recovery_started

        pdfs_linked = len(pdf_urls_unique)
        pdfs_opened = len(pdf_segments)

        # D-16 ladder: L2 whenever something quote-gated actually survived
        # (regardless of whether it came from the body or an attachment). L3
        # only when a PDF exists but every linked PDF failed for a genuine
        # readability reason (scan/image, encrypted, parse failure) and none
        # opened — the diagnosis "nobody can read this," never folded into
        # L1's "we have not read it yet." Anything else is L1_manuale.
        if requirements_recovered is not None and requirements_recovered >= 1:
            recovery_level = RecoveryLevel.L2_ESTRATTO
        elif pdfs_linked > 0 and pdfs_opened == 0 and pdf_illegible_count > 0:
            recovery_level = RecoveryLevel.L3_ILLEGGIBILE
        else:
            recovery_level = RecoveryLevel.L1_MANUALE

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
            recovery_level=recovery_level,
            pdfs_linked=pdfs_linked,
            pdfs_opened=pdfs_opened,
            pdfs_skipped=pdf_skipped,
            chars_processed=chars_processed,
            extraction_seconds=extraction_seconds,
            requirements_recovered=requirements_recovered,
        )

    def _collect_pdf_segments(
        self, pdf_urls: list[str]
    ) -> tuple[list[dict[str, Any]], list[str], list[PdfSkip], int]:
        """Download and extract text from up to `MAX_PDFS_PER_PAGE` attachments.

        `pypdf` is imported lazily (only pages that actually link a PDF pay
        this cost, matching `extract/llm.py`'s lazy-import convention for
        `anthropic`). Every skip — cap reached, too large, download failure,
        unreadable — is logged and returned as a human-readable note, per
        D-15: "log every skip explicitly."

        Also returns the D-16 skip audit (`PdfSkip` per skip) and how many of
        those skips were a genuine readability failure (parse failure or no
        extractable text) rather than a budget choice (cap reached, too
        large) or a transient network failure (download failed) — this
        distinction is what separates `L3_illeggibile` from a plain
        `L1_manuale` in `_normalise`.
        """
        notes: list[str] = []
        skipped: list[PdfSkip] = []
        illegible_count = 0
        if not pdf_urls:
            return [], notes, skipped, illegible_count

        def _skip(absolute_url: str, note: str, reason: str, *, illegible: bool) -> None:
            nonlocal illegible_count
            logger.info("skipping PDF %s: %s", absolute_url, reason)
            notes.append(note)
            skipped.append(PdfSkip(url=absolute_url, reason=reason))
            if illegible:
                illegible_count += 1

        ranked = sorted(dict.fromkeys(pdf_urls), key=_filename_rank)

        segments: list[dict[str, Any]] = []
        opened = 0
        for url in ranked:
            absolute_url = url if url.startswith("http") else f"{self.base_url}{url}"

            if opened >= MAX_PDFS_PER_PAGE:
                reason = f"limite di {MAX_PDFS_PER_PAGE} allegati per pagina raggiunto"
                _skip(
                    absolute_url,
                    f"Allegato PDF ignorato ({reason}): {absolute_url}",
                    reason,
                    illegible=False,
                )
                continue

            content_length = 0
            try:
                head = self._client.head(absolute_url)
                content_length = int(head.headers.get("content-length", 0) or 0)
            except Exception:
                content_length = 0  # HEAD unsupported/failed — fall through to GET

            if content_length and content_length > MAX_PDF_BYTES:
                reason = f"{content_length} byte, oltre il limite di {MAX_PDF_BYTES} byte"
                _skip(
                    absolute_url,
                    f"Allegato PDF ignorato (troppo grande, {reason}): {absolute_url}",
                    reason,
                    illegible=False,
                )
                continue

            try:
                response = self._client.get(absolute_url)
                response.raise_for_status()
            except Exception as exc:
                _skip(
                    absolute_url,
                    f"Allegato PDF non scaricabile: {absolute_url} ({exc})",
                    f"download fallito: {exc}",
                    illegible=False,
                )
                continue

            if len(response.content) > MAX_PDF_BYTES:
                reason = f"{len(response.content)} byte, oltre il limite di {MAX_PDF_BYTES} byte"
                _skip(
                    absolute_url,
                    f"Allegato PDF ignorato (troppo grande, {reason}): {absolute_url}",
                    reason,
                    illegible=False,
                )
                continue

            try:
                import pypdf  # lazy: only pages with a linked PDF pay this cost

                reader = pypdf.PdfReader(io.BytesIO(response.content))
                pages_text = [(p.extract_text() or "") for p in reader.pages]
            except Exception as exc:
                _skip(
                    absolute_url,
                    f"Allegato PDF illeggibile (parsing fallito): {absolute_url} ({exc})",
                    f"parsing fallito: {exc}",
                    illegible=True,
                )
                continue

            if not any(t.strip() for t in pages_text):
                reason = "nessun testo estraibile (probabile scansione/immagine)"
                _skip(
                    absolute_url,
                    f"Allegato PDF ignorato ({reason}): {absolute_url}",
                    reason,
                    illegible=True,
                )
                continue

            opened += 1
            segments.append({"kind": "allegato", "url": absolute_url, "pages": pages_text})

        return segments, notes, skipped, illegible_count
