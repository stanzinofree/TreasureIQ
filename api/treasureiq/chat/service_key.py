"""Deterministic recognition of a civic ``ServiceKey`` from citizen text.

Ramo 3, Slice 1.  Chat *recognises* the service key; it does not own the
vocabulary — the ``ServiceKey`` enum is a domain contract in
``catalog/service_contracts.py``, shared with the planner and the (future)
service cache/connectors.

The recogniser follows the same discipline as the intent scorer and
``_beneficiary_role_da_testo``: a closed set of markers, no language model, no
nearest-neighbour fallback.  It is a pure function so both intent backends
(``model`` and ``scorer``/``rust``) get the same result and the Rust oracle
(Slice 7) is not a prerequisite.
"""

from __future__ import annotations

import html
import re

from treasureiq.catalog.service_contracts import ServiceKey

#: Substring markers per service key (casefold, exact form — no stemming).
#: ``residenza`` on its own is deliberately absent: too generic (toponym /
#: "residenza" as a place), it produced false positives.  ``cie`` is NOT here
#: because it needs a whole-word match, not a substring (see ``_WORD_MARKERS``).
#: ``matrimonio`` on its own is deliberately absent for the same reason: bare
#: "matrimonio" over-matched distinct services ("pubblicazione di matrimonio",
#: the banns, is NOT the generic civil-registry key), so STATO_CIVILE keeps only
#: the unambiguous certificate phrases ("certificato di matrimonio", parallel to
#: nascita/morte).  A specific sub-service demands its own key, never a collapse.
_SUBSTRING_MARKERS: dict[ServiceKey, tuple[str, ...]] = {
    ServiceKey.CARTA_IDENTITA: (
        "carta d'identità",
        "carta d'identita",
        "carta di identità",
        "carta di identita",
    ),
    ServiceKey.CAMBIO_RESIDENZA: (
        "cambio residenza",
        "cambio di residenza",
        "trasferimento di residenza",
        "trasferimento residenza",
    ),
    ServiceKey.ACCESSO_ATTI: (
        "accesso agli atti",
        "accesso atti",
    ),
    ServiceKey.STATO_CIVILE: (
        "stato civile",
        "certificato di nascita",
        "certificato di morte",
        "certificato di matrimonio",
    ),
    ServiceKey.TRIBUTI: (
        "tributi",
        "tassa rifiuti",
    ),
}

#: Whole-word markers: acronyms/short tokens that would over-match as a
#: substring (``cie`` inside "società", ``imu``/``tari`` inside longer words).
_WORD_MARKERS: dict[ServiceKey, tuple[str, ...]] = {
    ServiceKey.CARTA_IDENTITA: ("cie",),
    ServiceKey.TRIBUTI: ("imu", "tari"),
}


#: Apostrophe variants folded to a plain ASCII ``'`` before matching.  Real
#: connector titles arrive as HTML (WP ``title.rendered``, ComWeb card markup):
#: entity-encoded (``&#8217;``, ``&#39;``) AND, once decoded, using the
#: typographic ``’`` (U+2019) that the ASCII markers would miss.  Without this
#: fold, "Carta d’identità" / "Carta d&#8217;identità" silently fail to confirm
#: (observed live: Borgaro, Lesa, Meina — false NOT_FOUND).
_APOSTROPHES = ("’", "‘", "ʼ", "`")


def _normalizza(message: str) -> str:
    """Decode HTML entities and fold apostrophe variants, then casefold.

    The single chokepoint every candidate title flows through, so both families
    (WP/AgID REST, ComWeb card HTML) confirm on the same canonical form without
    touching either connector.  Purely canonicalising: it never adds a marker,
    so it cannot create a false positive.  Idempotent on already-clean text
    (an unescaped, apostrophe-free string is unchanged).
    """
    testo = html.unescape(message)
    for apostrofo in _APOSTROPHES:
        testo = testo.replace(apostrofo, "'")
    return testo.casefold()


def _keys_in(message: str) -> set[ServiceKey]:
    haystack = _normalizza(message)
    found: set[ServiceKey] = set()
    for key, markers in _SUBSTRING_MARKERS.items():
        if any(marker in haystack for marker in markers):
            found.add(key)
    for key, words in _WORD_MARKERS.items():
        if any(re.search(rf"\b{re.escape(word)}\b", haystack) for word in words):
            found.add(key)
    return found


def riconosci_service_key(message: str) -> ServiceKey | None:
    """Return the service key marked in ``message``, or ``None``.

    Deterministic: same phrase → same key.  No marker → ``None`` (never the
    nearest service).  Two distinct keys marked in the same message → ``None``
    (ambiguous; disambiguation between services is the handler's job at a later
    slice, not the recogniser's — here the honest outcome is "undecided").
    """
    found = _keys_in(message)
    if len(found) == 1:
        return next(iter(found))
    return None
