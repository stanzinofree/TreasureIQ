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
import unicodedata

from treasureiq.catalog.service_contracts import (
    AzioneServizio,
    ServiceKey,
    VarianteServizio,
)

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
    # "paga"/"pagarla" volutamente esclusi: "la paga" (retribuzione) è un falso
    # segnale lessicale evitabile; "pagament"/"versament" (substring) e le forme
    # verbali sotto coprono il pagamento senza il rumore del sostantivo.
    AzioneServizio.PAGAMENTO: ("pago", "pagare", "paghi"),
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


# --------------------------------------------------------------------------- #
# VARIANT recogniser (Ramo 3, TARI MVP) — citizen side of the variant facet.
#
# TOPIC-SCOPED and exactly-one-or-``None``: a variant fires only when EXACTLY one
# signal family is present.  Zero families (no variant named) → ``None``; both
# families (ambiguous: home-business, "negozio di famiglia") → ``None``.  Fail-
# closed by construction: a ``None`` here means the facet does not narrow, so the
# connector keeps its ordinary exactly-one-or-NOT_FOUND behaviour (I-1 safe).  The
# measured profile on an adversarial held-out corpus was precision-when-fires
# 1.00 with zero cross-confusion and zero false-fire; recall degrades to ``None``
# on unseen vocabulary — the safe direction.
#
# Its own accent-stripping normaliser (distinct from ``_normalizza`` above, which
# preserves accents): the variant lexicon is written accent-free ("attivita",
# "societa"), so citizen accents are folded here to match it.  The candidate side
# (``facet_variante``) keeps its OWN slug vocabulary, apart from this one.


def _normalizza_variante(message: str) -> str:
    """Accent-stripped, non-alphanumeric-collapsed, space-padded haystack.

    NFKD + combining-mark removal folds ``à``→``a`` so the accent-free lexicon
    matches; every non-alphanumeric run becomes a single space and the string is
    space-padded, so word-boundary markers ("da casa") match without a regex.
    """
    folded = unicodedata.normalize("NFKD", message.lower())
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return " " + re.sub(r"[^a-z0-9]+", " ", stripped).strip() + " "


#: TARI DOMESTICHE signals (household waste tax): the citizen names a home.
_VARIANTE_TARI_DOM: tuple[str, ...] = (
    "domestica", "domestiche", "uso domestico", "abitazione", "appartamento",
    "casa mia", "mia casa", "di casa", "in casa", "della casa", "da casa",
    "nucleo familiare", "famiglia", "privato cittadino", "unita abitativa",
    "dove abito", "dove vivo", "prima casa", "seconda casa", "abito",
)
#: TARI NON_DOMESTICHE signals (business waste tax): the citizen names an activity.
#: Includes explicit-business forms that co-occur with "casa" (B&B, casa vacanze,
#: casa di riposo): on their own they are non-domestic; when a domestic signal also
#: fires (home-business) the two families co-fire → ``None`` (ambiguous, safe).
_VARIANTE_TARI_NONDOM: tuple[str, ...] = (
    "non domestica", "non domestiche", "utenza non domestica",
    "negozio", "attivita", "azienda", "ditta", "impresa", "societa",
    "bar", "ristorante", "pizzeria", "esercizio commerciale", "locale commerciale",
    "capannone", "ufficio", "studio professionale", "partita iva",
    "commerciale", "artigiano", "laboratorio", "magazzino", "opificio",
    "bed and breakfast", "affittacamere", "casa vacanze", "casa vacanza",
    "casa di riposo", "agriturismo", "b e b",
)
#: DOMESTICHE anti-markers: ``domestica``/``domestiche`` must NOT count for the
#: household family when it is the negated "non domestica" form (lexical overlap).
_VARIANTE_TARI_DOM_NEG: tuple[str, ...] = ("non domestica", "non domestiche")

#: CAMBIO_RESIDENZA INTERNO signals: change of dwelling within the SAME comune
#: (maps to the ``...residenza;abitazione`` slug).  Kept strict — bare "cambio
#: residenza"/"cambio casa" stay ambiguous (fire neither family → ``None``),
#: because a wrong scenario would promote the wrong card.
_VARIANTE_RES_INTERNO: tuple[str, ...] = (
    "stesso comune", "nello stesso comune", "stessa citta", "stesso paese",
    "cambio abitazione", "cambio di abitazione", "cambio indirizzo",
    "nuovo indirizzo", "cambio via", "cambio di via", "cambio strada",
    "cambio interno", "trasferimento interno",
)
#: CAMBIO_RESIDENZA IMMIGRAZIONE signals: moving in FROM another Italian comune
#: (maps to the ``...residenza;residenza`` slug).  Requires EXPLICIT inter-comune
#: evidence — generic origin markers ("vengo da", "trasferimento da", …) are
#: deliberately excluded: they also match intra-comune moves ("mi trasferisco da
#: via Roma a via Milano", "vengo da via Garibaldi") and would promote the wrong
#: ``;residenza`` card on a lone candidate (fail-closed violation).  With no
#: explicit inter-comune cue such phrasings fire neither family → ``None`` →
#: NOT_FOUND, which is the safe outcome.  ``estero``/``aire`` are vetoed upstream.
_VARIANTE_RES_IMMIGR: tuple[str, ...] = (
    "altro comune", "nuovo comune", "diverso comune", "altra citta",
    "immigrazione",
)

#: Per-key variant families: ``(A_family, A_neg, A_value, B_family, B_neg, B_value)``.
#: TOPIC-SCOPED — a key absent here never recognises a variant (strict ``None``).
_VARIANTE_FAMIGLIE: dict[
    ServiceKey,
    tuple[
        tuple[str, ...], tuple[str, ...], VarianteServizio,
        tuple[str, ...], tuple[str, ...], VarianteServizio,
    ],
] = {
    ServiceKey.TRIBUTI_TARI: (
        _VARIANTE_TARI_DOM, _VARIANTE_TARI_DOM_NEG, VarianteServizio.DOMESTICHE,
        _VARIANTE_TARI_NONDOM, (), VarianteServizio.NON_DOMESTICHE,
    ),
    ServiceKey.CAMBIO_RESIDENZA: (
        _VARIANTE_RES_INTERNO, (), VarianteServizio.INTERNO,
        _VARIANTE_RES_IMMIGR, (), VarianteServizio.IMMIGRAZIONE,
    ),
}

#: Per-key HARD veto: a deferred/out-of-scope scenario token anywhere in the
#: message forces a strict ``None`` (fail-closed), before any family fires.  This
#: is a true veto, unlike the per-family ``neg`` (which only cleans up lexical
#: overlap).  RESIDENZA vetoes estero/AIRE: the scenario is deferred, and
#: ``estero`` is directionally ambiguous (``all'estero`` emigration vs
#: ``dall'estero`` immigration), so any estero mention stays undecided.  Tokens are
#: space-padded where a bare stem could hit an unrelated word.
_VARIANTE_VETO: dict[ServiceKey, tuple[str, ...]] = {
    ServiceKey.CAMBIO_RESIDENZA: (" estero ", " aire ", "espatri", "emigra"),
}


def _famiglia_spara(haystack: str, famiglia: tuple[str, ...], neg: tuple[str, ...]) -> bool:
    """A signal family fires iff a marker is present AND not solely a negated form.

    If a marker matches but a negation substring is also present, the negated
    substrings are blanked and the family fires only if a marker STILL matches the
    remainder — so "non domestica" suppresses the household family, while
    "casa non domestica lontano" keeps it (a genuine second household marker).
    """
    if not any(m in haystack for m in famiglia):
        return False
    if neg and any(n in haystack for n in neg):
        ripulito = haystack
        for n in neg:
            ripulito = ripulito.replace(n, " ")
        return any(m in ripulito for m in famiglia)
    return True


def riconosci_variante(
    message: str, service_key: ServiceKey
) -> VarianteServizio | None:
    """Return the VARIANT marked in ``message`` for ``service_key``, or ``None``.

    Exactly-one-or-``None``, TOPIC-SCOPED: only keys with a variant vocabulary can
    ever fire (others → ``None``, a strict no-op).  One signal family present → its
    variant; zero families (no variant named) or both families (ambiguous) →
    ``None``.  No inference: a turn without an explicit-enough variant resolves to
    ``None``, and the connector's variant facet then stays inert (fail-closed, the
    ≥2 gate keeps its honest NOT_FOUND).
    """
    famiglie = _VARIANTE_FAMIGLIE.get(service_key)
    if famiglie is None:
        return None
    fam_a, neg_a, val_a, fam_b, neg_b, val_b = famiglie
    haystack = _normalizza_variante(message)
    veto = _VARIANTE_VETO.get(service_key)
    if veto and any(v in haystack for v in veto):
        return None
    a = _famiglia_spara(haystack, fam_a, neg_a)
    b = _famiglia_spara(haystack, fam_b, neg_b)
    if a and not b:
        return val_a
    if b and not a:
        return val_b
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
