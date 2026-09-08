"""Resolve-time ACTION facet over confirmed candidates (Ramo 3, facet-azione MVP).

A ``ServiceKey`` is topic granularity (IMU); the shared portals expose service
granularity (Pagamento IMU vs Dichiarazione IMU).  When a dense catalog confirms
≥2 candidates for one key, that is an honest NOT_FOUND under I-1 — but if the
citizen's turn also names an ACTION, the extra axis can narrow the set to exactly
one WITHOUT guessing.  This module is the CANDIDATE side of that axis: it reads
the action a portal title/slug OFFERS, mirroring how the shared recogniser reads
the key a title confirms.  The RECOGNISER side (what the citizen WANTS) lives in
``chat/service_key.py`` (``riconosci_azione``); keeping the two vocabularies
apart lets citizen phrasing and portal titling evolve independently.

Contract (never weakens I-1):

- The facet applies ONLY to keys in ``_FACET_KEYS`` and ONLY when the turn
  carries an action.  Otherwise it is a strict no-op (candidates unchanged).
- A candidate must offer *exactly* the requested action to survive.  0 or ≥2
  action markers on a candidate → actionless (``None``) → it is dropped, never
  guessed.  After the facet, 0 or ≥2 survivors fall back to the ordinary ≥2 gate
  (honest NOT_FOUND); the facet only ever promotes an exact single.

- ``;domanda`` — the Sportello launcher/submission suffix — is NOT an action and
  is excluded HARD: the slug segment after it is stripped before scanning, so a
  submission-form launcher can never masquerade as ``pagamento``/``dichiarazione``
  even if its vocabulary later grows.  The ``domand`` token that ``intento_azione``
  uses for DISAMBIGUATION grouping is deliberately not a marker here.
"""

from __future__ import annotations

from urllib.parse import unquote

from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_contracts import AzioneServizio, ServiceKey

#: Keys the action facet may narrow.  MVP: IMU only — the one tax whose portal
#: services fan out cleanly by action on the real corpus.  TARI/CIE/residenza and
#: the semantic splits are deferred sub-cycles; a key absent here is never
#: narrowed (the facet stays a no-op, so no behaviour change for it).
_FACET_KEYS: frozenset[ServiceKey] = frozenset({ServiceKey.TRIBUTI_IMU})

#: Candidate-side markers (casefold substring over title + slug).  Evidence-based
#: from the real corpus: portal titles read "Pagamento…"/"Versamento…"/"F24" and
#: "Dichiarazione…"; the Sportello slug carries ``;pagamento``/``;dichiarazione``
#: which these same substrings match inside the ``ns:slug;azione`` form.
_MARKERS: dict[AzioneServizio, tuple[str, ...]] = {
    AzioneServizio.PAGAMENTO: ("pagament", "versament", "f24"),
    AzioneServizio.DICHIARAZIONE: ("dichiaraz",),
}

#: The Sportello launcher marker.  A slug segment introduced by ``;domanda`` (or
#: the URL-encoded ``%3Bdomanda``) is a submission form, not an action: everything
#: from it onward is dropped before scanning so it can never leak an action.
_DOMANDA = "domanda"


def _testo_candidato(candidato: ServiceCandidate) -> str:
    """Title + decoded slug, casefolded, with any ``;domanda…`` launcher tail cut.

    The slug (``native_id``) may arrive URL-encoded (``%3B``=``;``, ``%3A``=``:``)
    and carry an action suffix after ``;``.  We decode it so the substring markers
    see ``;dichiarazione`` plainly, then cut a ``;domanda`` tail (hard exclusion).

    Casefold happens BEFORE the cut and the index is taken on that same casefolded
    string, so the offset can never mismatch the string it slices — casefold() can
    change length (``ß``→``ss``, ligatures), so folding-then-indexing-the-original
    would corrupt the cut on a non-ASCII slug.
    """
    slug = unquote(candidato.native_id).casefold()
    marcatore = f";{_DOMANDA}"
    taglio = slug.find(marcatore)
    if taglio != -1:
        # Drop from the launcher marker onward: the tail is a form, not an action.
        slug = slug[:taglio]
    return f"{candidato.title.casefold()}\n{slug}"


def azione_del_candidato(candidato: ServiceCandidate) -> AzioneServizio | None:
    """The action a candidate OFFERS, or ``None`` (0 or ≥2 markers → undecided).

    Exactly-one discipline, mirroring ``riconosci_azione``: an unmarked candidate
    is actionless, and a candidate that somehow matches two actions is undecided
    (``None``) rather than arbitrarily assigned — either way it will not equal the
    requested action and is dropped.
    """
    testo = _testo_candidato(candidato)
    trovate = {
        azione
        for azione, markers in _MARKERS.items()
        if any(marker in testo for marker in markers)
    }
    if len(trovate) == 1:
        return next(iter(trovate))
    return None


def facet_applicabile(service_key: ServiceKey, azione: AzioneServizio | None) -> bool:
    """Whether the action facet DECIDES this turn (turn has an action + facetable key).

    The caller uses this to make the facet authoritative when it applies: it then
    resolves to exactly-one or NOT_FOUND on its own, never falling back to the ≥2
    disambiguation branch (which would otherwise show the pre-facet candidates for
    a family that admits disambiguation).  When it returns ``False`` the facet is a
    strict no-op and the historic path is left byte-identical.  Distinct from
    ``filtra_per_azione`` returning ``confermati`` unchanged: that identity can
    also happen when every candidate already matches, which is NOT a no-op.
    """
    return azione is not None and service_key in _FACET_KEYS


def filtra_per_azione(
    confermati: tuple[ServiceCandidate, ...],
    service_key: ServiceKey,
    azione: AzioneServizio | None,
) -> tuple[ServiceCandidate, ...]:
    """Narrow confirmed candidates to those offering ``azione``.

    Strict no-op unless the key is facetable AND the turn carries an action:
    returns ``confermati`` unchanged, so every non-facet path keeps its exact
    prior behaviour.  When it does apply, only candidates whose offered action
    equals ``azione`` survive — 0 or ≥2 survivors are left for the caller's
    ordinary ≥2 gate (no arbitrary fallback).
    """
    if azione is None or service_key not in _FACET_KEYS:
        return confermati
    return tuple(c for c in confermati if azione_del_candidato(c) is azione)
