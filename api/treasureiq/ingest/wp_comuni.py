"""Connector for comuni running the "Design Comuni Italia" WordPress theme.

Background, because it drives every design choice here:

The Designers Italia model for municipal websites ships a WordPress theme that
defines a `servizio` post type with CMB2 metaboxes for the things a citizen
needs to know — what the service is, what documents to bring, and crucially
`_dci_servizio_vincoli`: the eligibility constraints.

Measured on Comune di Albano Laziale (32 services, August 2026):

    _dci_servizio_vincoli  present on 32/32,  filled on 1/32

Ten of those services are means-tested — ISEE appears in their prose — and
five state a numeric threshold, but always inside a free-text list rather than
the field built to hold it. So the structure exists and goes unused.

That is the gap TreasureIQ exists to expose. This connector therefore reads
the declared field when present (high confidence) and falls back to extracting
from prose (lower confidence), while recording which path it took so the
readiness score can report the ratio honestly.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from treasureiq.ingest.base import Connector
from treasureiq.schema import (
    Confidence,
    Opportunity,
    OpportunityKind,
    Requirements,
    Source,
    TargetGroup,
)

logger = logging.getLogger(__name__)

# CMB2 keys as actually served by the theme. Verified against live payloads
# rather than documentation, because deployments drift from the reference.
F_VINCOLI = "_dci_servizio_vincoli"
F_COSA_SERVE_INTRO = "_dci_servizio_cosa_serve_introduzione"
F_COSA_SERVE_LIST = "_dci_servizio_cosa_serve_list"
F_CANALE_DIGITALE_LINK = "_dci_servizio_canale_digitale_link"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# ISEE thresholds are written a dozen ways: "ISEE non superiore a 15.000,00 €",
# "ISEE fino ad € 9.360", "valore ISEE inferiore a euro 20000". This matches the
# family rather than one instance, and deliberately requires a proximity window
# so an unrelated number later in the paragraph is not captured.
_ISEE_RE = re.compile(
    r"ISEE\b[^.;\n]{0,80}?"
    r"(?:non\s+superiore\s+a|inferiore\s+a|fino\s+a(?:d)?|massimo\s+di|entro|<=?)"
    r"[^\d]{0,15}"
    r"(?P<amount>\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d{4,6}(?:,\d{1,2})?)",
    re.IGNORECASE,
)

_AGE_RE = re.compile(
    r"(?:et[àa]\s+(?:compresa\s+tra|tra)\s+(?P<min1>\d{1,3})\s*(?:e|-)\s*(?P<max1>\d{1,3}))"
    r"|(?:(?:maggiori|over|superiore\s+ai?)\s+(?P<min2>\d{1,3})\s*anni)"
    r"|(?:(?:minori|under|inferiore\s+ai?)\s+(?P<max2>\d{1,3})\s*anni)"
    # "devono aver compiuto 18 anni" — the phrasing Albano actually uses on
    # its one populated constraints field, and the standard way Italian
    # municipal text states a minimum age. Missing it made the regex look
    # worse than it is and, worse, made the comune's score look worse too.
    r"|(?:(?:aver\s+)?compiut[oi]\s+(?:i\s+)?(?P<min3>\d{1,3})\s*anni)",
    re.IGNORECASE,
)

# Category slug -> our taxonomy. The theme's own vocabulary, mapped rather than
# replaced, so a comune's existing categorisation keeps its meaning.
_CATEGORY_TARGETS: dict[str, list[TargetGroup]] = {
    "scuola": [TargetGroup.STUDENTI, TargetGroup.FAMIGLIE],
    "istruzione": [TargetGroup.STUDENTI, TargetGroup.FAMIGLIE],
    "sociale": [TargetGroup.FAMIGLIE],
    "famiglia": [TargetGroup.FAMIGLIE],
    "salute": [TargetGroup.TUTTI],
    "anziani": [TargetGroup.ANZIANI],
    "disabilita": [TargetGroup.DISABILITA],
    "lavoro": [TargetGroup.DISOCCUPATI],
    "imprese": [TargetGroup.IMPRESE],
}

_KIND_KEYWORDS: list[tuple[re.Pattern[str], OpportunityKind]] = [
    (re.compile(r"\bvoucher\b", re.I), OpportunityKind.VOUCHER),
    (re.compile(r"contribut|sussid|borsa\b|bonus\b", re.I), OpportunityKind.CONTRIBUTO_ECONOMICO),
    (re.compile(r"agevolaz|esenzion|riduzion", re.I), OpportunityKind.AGEVOLAZIONE),
    (re.compile(r"\bbando\b|\bavviso\s+pubblico\b", re.I), OpportunityKind.BANDO),
]


def strip_html(raw: Any) -> str:
    """Flatten a CMB2 field to plain text.

    Accepts `Any` rather than `str` because the same theme field is served with
    different shapes across records: `_dci_servizio_cosa_serve_list` arrives as
    an HTML string on some services and as a JSON array of strings on others,
    depending on how the editor filled the repeatable group. Both occur in a
    single comune's catalogue, so tolerating the variation is not defensive
    programming — it is the actual contract.

    List items are separated with ' | ' rather than a space: they are distinct
    requirements, and running them together would let the ISEE proximity regex
    match a number belonging to a different bullet.
    """
    if raw is None or raw == "":
        return ""
    if isinstance(raw, (list, tuple)):
        return " | ".join(part for part in (strip_html(item) for item in raw) if part)
    if isinstance(raw, dict):
        return " | ".join(part for part in (strip_html(v) for v in raw.values()) if part)
    if not isinstance(raw, str):
        raw = str(raw)
    text = re.sub(r"</li>|<br\s*/?>|</p>", " | ", raw, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    # WordPress emits both named and numeric entities, and `wptexturize` adds
    # typographic ones (&#8220;, &#8217;) that a hand-written replacement table
    # will always trail. Decode twice: titles are routinely double-encoded when
    # editors paste from Word, leaving '&amp;#8220;' in the payload.
    text = html.unescape(html.unescape(text))
    text = text.replace("\xa0", " ")
    text = _WS_RE.sub(" ", text)
    text = re.sub(r"(\s*\|\s*)+", " | ", text).strip(" |")
    return text.strip()


def parse_euro(amount: str) -> Decimal | None:
    """Parse Italian-formatted currency: '15.000,00' -> Decimal('15000.00').

    Returns `Decimal`, not `float`, because these values are compared against a
    citizen's ISEE to decide eligibility. Binary floating point would make a
    threshold comparison at the boundary non-deterministic, and "your ISEE is
    one cent over" is exactly the case that must be exact.
    """
    cleaned = amount.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def extract_requirements(text: str) -> tuple[Requirements, list[str]]:
    """Best-effort recovery of eligibility criteria from prose.

    Returns the requirements plus notes on what stayed ambiguous. The notes are
    shown to the citizen: when the machine guessed, they deserve to know.

    This is intentionally conservative. A missed criterion sends a citizen to
    read the source page — mildly annoying. An invented one sends them to file
    an application they cannot win, which is how a tool like this loses trust.
    """
    req = Requirements()
    notes: list[str] = []

    isee_match = _ISEE_RE.search(text)
    if isee_match:
        value = parse_euro(isee_match.group("amount"))
        # Municipal ISEE thresholds cluster between ~3k and ~65k. Outside that
        # band the number is almost certainly something else caught by the
        # window — an amount granted, a protocol number, a year.
        if value is not None and Decimal(1000) <= value <= Decimal(100000):
            req.isee_max = value.quantize(Decimal("0.01"))
        elif value is not None:
            notes.append(
                f"Trovato un valore ISEE implausibile ({value:g} EUR): ignorato."
            )
    elif re.search(r"\bISEE\b", text, re.IGNORECASE):
        # Means-tested but no threshold published: the single most common data
        # gap, and the one that makes automated matching impossible.
        notes.append(
            "Il servizio richiede l'ISEE ma non pubblica la soglia: "
            "verifica sulla pagina del comune."
        )
        req.other.append("Richiesta attestazione ISEE (soglia non pubblicata)")

    age_match = _AGE_RE.search(text)
    if age_match:
        groups = age_match.groupdict()
        if groups.get("min1") and groups.get("max1"):
            req.eta_min, req.eta_max = int(groups["min1"]), int(groups["max1"])
        elif groups.get("min2"):
            req.eta_min = int(groups["min2"])
        elif groups.get("max2"):
            req.eta_max = int(groups["max2"])
        elif groups.get("min3"):
            req.eta_min = int(groups["min3"])

    if re.search(r"disabilit|handicap|legge\s*104", text, re.IGNORECASE):
        req.disabilita_required = True
    if re.search(r"figli\s+minor|minori\s+a\s+carico", text, re.IGNORECASE):
        req.figli_minori_required = True

    return req, notes


def guess_kind(title: str, body: str) -> OpportunityKind:
    """Classify from the title first, falling back to body text.

    Title-first because Italian service pages routinely mention neighbouring
    instruments in their body ("in alternativa al bonus..."), which misleads a
    whole-document match.
    """
    for pattern, kind in _KIND_KEYWORDS:
        if pattern.search(title):
            return kind
    for pattern, kind in _KIND_KEYWORDS:
        if pattern.search(body):
            return kind
    return OpportunityKind.SERVIZIO


class WPComuniConnector(Connector):
    """Ingests `servizio` records from a Design Comuni Italia WordPress site."""

    name = "wp_rest"
    transport_quality = 0.8  # typed JSON over HTTP, stable field names

    def __init__(
        self,
        *,
        base_url: str,
        ente: str,
        codice_istat: str,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.ente = ente
        self.codice_istat = codice_istat
        self.stats.source_id = f"{self.name}:{codice_istat}"

    @property
    def api_root(self) -> str:
        return f"{self.base_url}/wp-json/wp/v2"

    def fetch(self) -> list[Opportunity]:
        opportunities: list[Opportunity] = []
        for record in self._iter_servizi():
            self.stats.records_seen += 1
            try:
                opportunity = self._normalise(record)
            except Exception as exc:  # one bad record must not kill the run
                msg = f"servizio id={record.get('id')}: {exc}"
                logger.warning("normalisation failed for %s", msg)
                self.stats.errors.append(msg)
                continue
            opportunities.append(opportunity)
            self.stats.records_emitted += 1
            if opportunity.confidence is Confidence.DECLARED:
                self.stats.with_declared_requirements += 1
            elif not opportunity.requirements.is_empty:
                self.stats.with_extracted_requirements += 1
            if opportunity.deadline:
                self.stats.with_deadline += 1
        return opportunities

    def _iter_servizi(self) -> list[dict[str, Any]]:
        """Page through the servizi collection.

        Trusts `X-WP-TotalPages` but caps iterations: a misconfigured site that
        echoes the same header forever would otherwise loop indefinitely.
        """
        collected: list[dict[str, Any]] = []
        page = 1
        total_pages = 1
        while page <= total_pages and page <= 50:
            payload, headers = self._get_json(
                f"{self.api_root}/servizi", per_page=100, page=page
            )
            if not isinstance(payload, list):
                self.stats.errors.append(f"page {page}: unexpected payload shape")
                break
            collected.extend(payload)
            if page == 1:
                total_pages = int(headers.get("X-WP-TotalPages", 1) or 1)
            page += 1
        return collected

    def _normalise(self, record: dict[str, Any]) -> Opportunity:
        cmb2 = record.get("cmb2") or {}
        # CMB2 nests fields under box names that vary by theme version, so
        # flatten rather than hardcoding the box level.
        flat: dict[str, Any] = {}
        for box in cmb2.values():
            if isinstance(box, dict):
                flat.update(box)

        title = strip_html(record.get("title", {}).get("rendered", "")).strip()

        vincoli = strip_html(flat.get(F_VINCOLI))
        intro = strip_html(flat.get(F_COSA_SERVE_INTRO))
        needs = strip_html(flat.get(F_COSA_SERVE_LIST))
        body = " | ".join(part for part in (intro, needs, vincoli) if part)

        # The declared constraints field wins when the comune filled it: that
        # is the whole point of the standard. Prose extraction is the fallback,
        # and the confidence level records which happened.
        if vincoli:
            requirements, notes = extract_requirements(vincoli)
            confidence = Confidence.DECLARED
        else:
            requirements, notes = extract_requirements(body)
            confidence = (
                Confidence.EXTRACTED if not requirements.is_empty else Confidence.INFERRED
            )
            notes.append(
                "Il comune non compila il campo 'vincoli' previsto dal modello "
                "Design Comuni Italia: requisiti dedotti dal testo."
            )

        targets: list[TargetGroup] = []
        for slug in record.get("class_list", []) or []:
            key = slug.replace("categorie_servizio-", "")
            targets.extend(_CATEGORY_TARGETS.get(key, []))
        targets = list(dict.fromkeys(targets)) or [TargetGroup.TUTTI]

        # WordPress `date` is the publication timestamp in site-local time.
        # It is not an application window, so it maps to `opens_at` only as a
        # freshness signal — `deadline` stays None unless the comune states one,
        # because inventing a deadline would be worse than admitting there
        # isn't a published one.
        opens_at: date | None = None
        raw_date = record.get("date")
        if isinstance(raw_date, str) and raw_date:
            try:
                opens_at = datetime.fromisoformat(raw_date).date()
            except ValueError:
                notes.append(f"Data di pubblicazione non interpretabile: {raw_date}")

        source_url = record.get("link") or self.base_url
        return Opportunity(
            opens_at=opens_at,
            id=f"{self.name}:{self.codice_istat}:{record.get('id')}",
            title=title,
            summary=intro or needs or None,
            body=body or None,
            kind=guess_kind(title, body),
            targets=targets,
            requirements=requirements,
            source=Source(
                ente=self.ente,
                ente_codice_istat=self.codice_istat,
                connector=self.name,
                url=source_url,
                api_url=f"{self.api_root}/servizi/{record.get('id')}",
                fetched_at=self.now(),
                raw_hash=self.hash_payload(record),
            ),
            confidence=confidence,
            extraction_notes=notes,
        )
