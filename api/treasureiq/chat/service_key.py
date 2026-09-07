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

from treasureiq.catalog.service_contracts import AzioneServizio, ServiceKey

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
        # Apostrophe elided to a bare space when typed ("carta d identità").
        # Still high-confidence: "identit…" is explicit, so no collision with
        # "carta di credito"/"carta di soggiorno". Bare "carta" stays unmatched.
        "carta d identità",
        "carta d identita",
    ),
    ServiceKey.CAMBIO_RESIDENZA: (
        "cambio residenza",
        "cambio di residenza",
        "cambiare residenza",
        "cambiare la residenza",
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
    # No bare "tributi" substring: it leaked onto "contributi"/"contributiva"
    # (grants, a different service) and did not discriminate a tax anyway.
    ServiceKey.TRIBUTI_TARI: (
        "tassa rifiuti",
    ),
}

#: Whole-word markers: acronyms/short tokens that would over-match as a
#: substring (``cie`` inside "società", ``imu``/``tari`` inside longer words).
_WORD_MARKERS: dict[ServiceKey, tuple[str, ...]] = {
    ServiceKey.CARTA_IDENTITA: ("cie",),
    ServiceKey.TRIBUTI_IMU: ("imu",),
    ServiceKey.TRIBUTI_TARI: ("tari",),
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


#: Citizen-side markers for the ACTION axis (facet-azione MVP).  Same discipline
#: as the ServiceKey markers: a closed set, casefold, no stemming, no nearest
#: neighbour.  This is the RECOGNISER side (what the citizen wants); the CANDIDATE
#: side (what a portal title/slug offers) has its own vocabulary in
#: ``service_connectors/facet_azione.py`` — kept separate so citizen phrasing and
#: portal titling evolve independently (exactly like the ServiceKey split between
#: recogniser markers and ``SERVICE_SEARCH_TERM``).
#:
#: ``;domanda`` (the Sportello launcher marker) is NOT an action and appears in
#: none of these lists on purpose: it is a submission-form suffix, not a verb the
#: citizen would type, and the ``domand`` token used by ``intento_azione`` for
#: DISAMBIGUATION grouping is deliberately not reused here.
_AZIONE_SUBSTRING: dict[AzioneServizio, tuple[str, ...]] = {
    AzioneServizio.PAGAMENTO: ("pagament", "versament", "f24"),
    AzioneServizio.DICHIARAZIONE: ("dichiaraz",),
}

#: Whole-word markers: short verb forms that would over-match as a substring
#: (``pago`` inside "pagola", ``paga`` inside "pagatore").
_AZIONE_WORD: dict[AzioneServizio, tuple[str, ...]] = {
    AzioneServizio.PAGAMENTO: ("pago", "pagare", "paga", "paghi", "pagarla"),
    AzioneServizio.DICHIARAZIONE: ("dichiaro", "dichiarare", "denuncia", "denunciare"),
}


def _azioni_in(message: str) -> set[AzioneServizio]:
    haystack = _normalizza(message)
    found: set[AzioneServizio] = set()
    for azione, markers in _AZIONE_SUBSTRING.items():
        if any(marker in haystack for marker in markers):
            found.add(azione)
    for azione, words in _AZIONE_WORD.items():
        if any(re.search(rf"\b{re.escape(word)}\b", haystack) for word in words):
            found.add(azione)
    return found


def riconosci_azione(message: str) -> AzioneServizio | None:
    """Return the ACTION marked in ``message``, or ``None`` (facet-azione MVP).

    Same honesty as ``riconosci_service_key``: no marker → ``None`` (the turn is
    actionless, never the nearest action); two distinct actions in one message →
    ``None`` (ambiguous → the facet does not narrow, the ≥2 gate decides).  A
    ``None`` here means the facet is a no-op: the connector keeps its ordinary
    exactly-one-or-NOT_FOUND behaviour.
    """
    found = _azioni_in(message)
    if len(found) == 1:
        return next(iter(found))
    return None


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
