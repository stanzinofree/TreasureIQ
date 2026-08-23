"""Structured evidence read from a municipal service page (Ramo 3, Slice 4).

This is a normaliser of already-acquired data, not a generic scraper and not a
full document extractor.  It takes the HTML of one service page (fetched
elsewhere, behind the connector's fetch seam) and returns typed link evidence:
downloadable forms and authenticated-online entrypoints found *on that page*.

Provenance policy (imposed here, not by the connector):
- DOWNLOAD: only ``.pdf``/``.doc``/``.docx``/``.odt`` and only on the official
  host — a form is the comune's own file, not a third party's.
- AUTHENTICATED_ONLINE: only links whose anchor text or nearby context is an
  explicit online/authenticated-service call; a bare "Area personale" menu link
  is not evidence.  The host may be external (a comune legitimately links URBI,
  Municipium, …) — the connector never follows nor authenticates it.
- Never ``javascript:``/``data:``/``mailto:``/fragment-only/non-HTTP(S) links.

The parser does no network I/O and does not build ``ServiceAccessOption``: it
returns evidence only.  Turning evidence into access options is the connector's
job.
"""

from __future__ import annotations

import html as _html
import re
from enum import Enum
from urllib.parse import urljoin, urlparse

from pydantic import AnyHttpUrl, Field

from treasureiq.catalog.contracts import _StrictModel
from treasureiq.catalog.service_contracts import AuthenticationMethod

#: Extensions that count as a downloadable form (casefolded, on the URL path).
_DOWNLOAD_SUFFIXES: tuple[str, ...] = (".pdf", ".doc", ".docx", ".odt")

#: Explicit online/authenticated-service phrases.  A generic "area personale"
#: is deliberately absent: on its own it is a nav-menu link, not evidence that
#: THIS service is available online (review of Slice 4).
_AUTH_MARKERS: tuple[str, ...] = (
    "accedi al servizio",
    "accedi al portale",
    "accedi con spid",
    "accedi con cie",
    "accedi con la tua identità",
    "accedi all'area riservata",
    "servizio online",
    "presenta la domanda online",
    "invia la domanda online",
    "compila la domanda online",
    "richiesta online",
    "domanda online",
    "attiva il servizio online",
)

#: Authentication methods, detected only when explicitly named in the evidence.
_AUTH_METHOD_MARKERS: tuple[tuple[str, AuthenticationMethod], ...] = (
    ("spid", AuthenticationMethod.SPID),
    ("cie", AuthenticationMethod.CIE),
    ("cns", AuthenticationMethod.CNS),
)

_ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_TITLE_RE = re.compile(r"""title\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_ARIA_LABEL_RE = re.compile(r"""aria-label\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

#: Block-level boundaries.  Context is read back only to the nearest one before
#: the anchor, so an "servizio online" phrase in a DIFFERENT block/section can
#: never be misread as evidence for a generic link — the evidence must be in the
#: link's own immediate container (review of Slice 4: contextual, not merely
#: "text that happens to appear a little earlier in the HTML").
_BLOCK_BOUNDARY_RE = re.compile(
    r"</?(?:p|li|div|td|th|tr|table|section|article|ul|ol|dl|dd|dt"
    r"|h[1-6]|nav|header|footer|main|aside|figure|figcaption|form)\b[^>]*>",
    re.IGNORECASE,
)

#: Hard cap on the lookback, applied BEFORE the block boundary is found (a
#: pathological block with no boundary tags still can't drag in the whole page).
_CONTEXT_WINDOW = 300


class EvidenceKind(str, Enum):
    DOWNLOAD = "download"
    AUTHENTICATED_ONLINE = "authenticated_online"


class LinkEvidence(_StrictModel):
    """One typed link found on a service page — evidence, not an access option."""

    url: AnyHttpUrl
    kind: EvidenceKind
    anchor_text: str = Field(min_length=1)
    context_text: str | None = None
    authentication: tuple[AuthenticationMethod, ...] = ()


class PaginaServizio(_StrictModel):
    """The typed evidence extracted from one service page."""

    page_url: AnyHttpUrl
    links: tuple[LinkEvidence, ...] = ()


def _testo(frammento: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", frammento))).strip()


def _host(url: str) -> str:
    """Registrable-ish host without a leading ``www.`` (same rule as the map)."""
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _e_scaricabile(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(_DOWNLOAD_SUFFIXES)


def _metodi_auth(testo: str) -> tuple[AuthenticationMethod, ...]:
    basso = testo.casefold()
    metodi = tuple(
        metodo
        for marker, metodo in _AUTH_METHOD_MARKERS
        if re.search(rf"\b{re.escape(marker)}\b", basso)
    )
    # Preserve declaration order, drop duplicates.
    visti: list[AuthenticationMethod] = []
    for metodo in metodi:
        if metodo not in visti:
            visti.append(metodo)
    return tuple(visti)


def _e_accesso_online(testo: str) -> bool:
    basso = testo.casefold()
    return any(marker in basso for marker in _AUTH_MARKERS)


def _contesto_contenitore(html: str, anchor_start: int) -> str:
    """Text of the anchor's immediate container, back to the nearest block
    boundary (capped by ``_CONTEXT_WINDOW``).  Not the whole page, not a flat
    N-char window that straddles sections."""
    finestra = html[max(0, anchor_start - _CONTEXT_WINDOW) : anchor_start]
    ultimo = None
    for m in _BLOCK_BOUNDARY_RE.finditer(finestra):
        ultimo = m
    if ultimo is not None:
        finestra = finestra[ultimo.end() :]
    return _testo(finestra)


def leggi_pagina_servizio(
    html: str,
    *,
    page_url: str,
    official_host: str,
) -> PaginaServizio:
    """Extract typed link evidence from one service page's HTML.

    ``page_url`` resolves relative links (``urljoin``); ``official_host`` gates
    the same-host DOWNLOAD policy.  Deterministic: same HTML → same evidence,
    in document order, deduplicated by ``(url, kind)``.  No network I/O.
    """
    host_ufficiale = official_host[4:] if official_host.lower().startswith("www.") else official_host.lower()
    links: list[LinkEvidence] = []
    visti: set[tuple[str, EvidenceKind]] = set()

    for match in _ANCHOR_RE.finditer(html):
        attrs, inner = match.group(1), match.group(2)
        href_match = _HREF_RE.search(attrs)
        if href_match is None:
            continue
        href = href_match.group(1).strip()
        if not href or href.startswith("#"):
            continue

        assoluto = urljoin(page_url, href)
        parsed = urlparse(assoluto)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue

        anchor_text = _testo(inner)
        if not anchor_text:
            continue
        # Evidence is the link's own context: anchor text, its aria-label/title
        # attributes, and the immediate container block — not a flat lookback.
        title_match = _TITLE_RE.search(attrs)
        aria_match = _ARIA_LABEL_RE.search(attrs)
        attributi = " ".join(
            _testo(m.group(1)) for m in (aria_match, title_match) if m is not None
        )
        contenitore = _contesto_contenitore(html, match.start())
        contesto = " ".join(p for p in (contenitore, attributi) if p) or None
        combinato = f"{contenitore} {attributi} {anchor_text}"

        kind: EvidenceKind | None = None
        autenticazione: tuple[AuthenticationMethod, ...] = ()
        if _e_scaricabile(assoluto):
            # A form is the comune's own file: same-host only.
            if _host(assoluto) == host_ufficiale:
                kind = EvidenceKind.DOWNLOAD
        elif _e_accesso_online(combinato):
            # Online service: external host allowed (URBI/Municipium/…).
            kind = EvidenceKind.AUTHENTICATED_ONLINE
            autenticazione = _metodi_auth(combinato)

        if kind is None:
            continue
        chiave = (assoluto, kind)
        if chiave in visti:
            continue
        visti.add(chiave)
        links.append(
            LinkEvidence(
                url=assoluto,
                kind=kind,
                anchor_text=anchor_text,
                context_text=contesto or None,
                authentication=autenticazione,
            )
        )

    return PaginaServizio(page_url=page_url, links=tuple(links))
