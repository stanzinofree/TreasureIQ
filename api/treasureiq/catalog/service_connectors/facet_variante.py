"""Resolve-time VARIANT facet over confirmed candidates (Ramo 3, TARI MVP).

A second narrowing axis alongside the ACTION facet (``facet_azione``), for topics
whose portal services fan out by a *semantic variant* the action cannot tell
apart.  TARI is the motivating case: on the real corpus the declaration splits
into ``utenze.domestiche`` (household) and ``utenze.non.domestiche`` (business),
BOTH carrying the same action (``dichiarazione``) — so the action facet alone
leaves an honest ≥2 NOT_FOUND, and it is the variant that narrows the pair to
exactly one.

This module is the CANDIDATE side of that axis: it reads the variant a portal
slug OFFERS, mirroring how the citizen-side recogniser (``chat/service_key.py``,
``riconosci_variante``) reads the variant the citizen WANTS.  Keeping the two
vocabularies apart lets citizen phrasing and portal slugging evolve independently
— exactly as ``facet_azione`` keeps its markers apart from ``riconosci_azione``.

Contract (never weakens I-1, composes with — never replaces — the action facet):

- TOPIC-SCOPED.  The variant vocabulary is per-key (``_VARIANT_MARKERS``): TARI's
  domestiche/non.domestiche do not generalise to other topics, so a key absent
  from that table is never narrowed (the facet stays a strict no-op for it).  MVP
  covers TARI (domestiche/non.domestiche) and CAMBIO_RESIDENZA (interno/
  immigrazione); estero/AIRE, convivenza, comunitari and CIE are deferred.

- The facet applies ONLY to keys in ``_VARIANT_MARKERS`` and ONLY when the turn
  carries a variant.  Otherwise it is a strict no-op (candidates unchanged), so
  every historic path — IMU included — stays byte-identical.

- A candidate must offer *exactly* the requested variant to survive.  0 or ≥2
  variant markers on a candidate → variantless (``None``) → dropped, never
  guessed.  After the facet, 0 or ≥2 survivors fall back to the ordinary ≥2 gate
  (honest NOT_FOUND); the facet only ever promotes an exact single.

- Marker OVERLAP is handled explicitly.  ``utenze.non.domestiche`` contains the
  substring ``domestiche``, so the domestic marker carries an anti-marker
  (``non.domestiche``) that suppresses it when the non-domestic form is present.
  This keeps the two variants mutually exclusive on a slug and preserves the
  exactly-one discipline (a non-domestic slug reads as exactly NON_DOMESTICHE,
  not as an ambiguous both → ``None``).

- ``;domanda`` — the Sportello launcher/submission suffix — is stripped before
  scanning, identically to ``facet_azione``: a submission-form launcher never
  leaks a variant.
"""

from __future__ import annotations

from urllib.parse import unquote

from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_contracts import ServiceKey, VarianteServizio

#: The Sportello launcher marker (mirrors ``facet_azione._DOMANDA``): a slug
#: segment from ``;domanda`` onward is a submission form, not a variant.
_DOMANDA = "domanda"

#: Per-key, TOPIC-SCOPED variant markers over the candidate's title + decoded
#: slug (casefold substring).  Each entry is ``(variant, markers, anti)``: the
#: variant fires when any ``marker`` matches AND no ``anti`` marker matches.  The
#: ``anti`` list is what makes overlapping substrings mutually exclusive.
#:
#: TARI evidence (real corpus): the Sportello slug reads
#: ``tassa.rifiuti;utenze.domestiche;dichiarazione`` /
#: ``tassa.rifiuti;utenze.non.domestiche;dichiarazione``.  Non-domestic is checked
#: with no anti-marker; domestic carries ``non.domestiche`` as anti so the shared
#: ``domestiche`` substring cannot double-fire it.
#:
#: RESIDENZA evidence (17-comune recon, national ``s_italia`` taxonomy): the change
#: family shares base ``cambio.abitazione.residenza`` and splits on the TRAILING
#: segment — ``;abitazione`` (cambio interno, exactly-1/host) vs ``;residenza``
#: (immigrazione da altro comune, exactly-1/host) vs ``;dichiarazione`` (the action
#: axis, matches neither variant → ``None``).  The markers carry the leading ``;``
#: so they anchor on that segment: the base's dot-separated ``.abitazione.`` and
#: ``.residenza`` cannot double-fire, so no anti-marker is needed.  ``estero`` is
#: deferred (candidate set 2 + directional ambiguity — see ``VarianteServizio``).
_VARIANT_MARKERS: dict[ServiceKey, tuple[tuple[VarianteServizio, tuple[str, ...], tuple[str, ...]], ...]] = {
    ServiceKey.TRIBUTI_TARI: (
        (VarianteServizio.NON_DOMESTICHE, ("non.domestiche",), ()),
        (VarianteServizio.DOMESTICHE, ("domestiche",), ("non.domestiche",)),
    ),
    ServiceKey.CAMBIO_RESIDENZA: (
        (VarianteServizio.INTERNO, (";abitazione",), ()),
        (VarianteServizio.IMMIGRAZIONE, (";residenza",), ()),
    ),
}


def _testo_candidato(candidato: ServiceCandidate) -> str:
    """Title + decoded slug, casefolded, with any ``;domanda…`` launcher tail cut.

    Identical discipline to ``facet_azione._testo_candidato``: decode the possibly
    URL-encoded ``native_id`` so ``;utenze.non.domestiche`` reads plainly, casefold
    BEFORE cutting so the ``;domanda`` index cannot mismatch the sliced string.
    """
    slug = unquote(candidato.native_id).casefold()
    taglio = slug.find(f";{_DOMANDA}")
    if taglio != -1:
        slug = slug[:taglio]
    return f"{candidato.title.casefold()}\n{slug}"


def variante_del_candidato(
    candidato: ServiceCandidate, service_key: ServiceKey
) -> VarianteServizio | None:
    """The variant a candidate OFFERS, or ``None`` (0 or ≥2 markers → undecided).

    Topic-scoped: a key without a variant vocabulary is always ``None`` (no-op).
    Exactly-one discipline, mirroring ``variante_del_candidato``'s citizen twin:
    an unmarked candidate is variantless, and a candidate that somehow matches two
    variants is undecided (``None``) rather than arbitrarily assigned — either way
    it will not equal the requested variant and is dropped.
    """
    spec = _VARIANT_MARKERS.get(service_key)
    if spec is None:
        return None
    testo = _testo_candidato(candidato)
    trovate = {
        variante
        for variante, markers, anti in spec
        if any(m in testo for m in markers) and not any(a in testo for a in anti)
    }
    if len(trovate) == 1:
        return next(iter(trovate))
    return None


def variante_applicabile(
    service_key: ServiceKey, variante: VarianteServizio | None
) -> bool:
    """Whether the variant facet DECIDES this turn (turn has a variant + scoped key).

    Parallel to ``facet_azione.facet_applicabile``.  When ``True`` the caller lets
    the composed narrowing resolve to exactly-one or NOT_FOUND on its own, never
    falling back to the ≥2 disambiguation branch.  When ``False`` the facet is a
    strict no-op and the historic path is left byte-identical.
    """
    return variante is not None and service_key in _VARIANT_MARKERS


def filtra_per_variante(
    confermati: tuple[ServiceCandidate, ...],
    service_key: ServiceKey,
    variante: VarianteServizio | None,
) -> tuple[ServiceCandidate, ...]:
    """Narrow confirmed candidates to those offering ``variante``.

    Strict no-op unless the key is variant-scoped AND the turn carries a variant:
    returns ``confermati`` unchanged, so every non-variant path (IMU, actionless
    TARI, any other key) keeps its exact prior behaviour.  When it does apply,
    only candidates whose offered variant equals ``variante`` survive — 0 or ≥2
    survivors are left for the caller's ordinary ≥2 gate (no arbitrary fallback).
    Composable with ``filtra_per_azione``: applying both in sequence narrows by
    action then by variant, each a no-op when its own axis is inert.
    """
    if variante is None or service_key not in _VARIANT_MARKERS:
        return confermati
    return tuple(
        c for c in confermati if variante_del_candidato(c, service_key) is variante
    )
