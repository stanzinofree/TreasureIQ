"""Legacy-shaped bridge from the production recognition registry.

The runtime selects a connector from a :class:`Firma` (``piattaforma`` enum +
verbatim ``prova``). The recognition registry instead returns a
:class:`RecognitionMatch` whose ``platform_id`` is a string. This adapter is the
one seam that maps the registry's answer back onto the legacy ``Firma`` so the
BASE dispatch (``connettore``) and the AT confirmation keep working — now driven
by the 7 native plugins + Passo C suppression rather than by ``classifica_risposta``
directly.

Scope is deliberately **BASE and AT only** (Gate 0 in the T2 planning doc). The
native SP plugins emit ``municipium_portalegen`` / ``filodiretto``, which are not
members of :class:`Piattaforma`; wiring ``SERVICE_PORTAL`` through the legacy
vocabulary would silently collapse those identities to ``IGNOTA``. Until the SP
vocabulary is settled, this adapter refuses ``Surface.SERVICE_PORTAL`` outright.

``classifica_risposta`` is untouched: the registry wraps it via the legacy
bridge, it does not replace it.
"""

from __future__ import annotations

import logging

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition_bridge import build_recognition_registry
from treasureiq.catalog.recognition_plugins import RecognitionObservation
from treasureiq.catalog.recognition_registry import RecognitionMatch
from treasureiq.ingest.piattaforma import Firma, Piattaforma

logger = logging.getLogger(__name__)

#: Surfaces the legacy ``Firma`` vocabulary can represent. SERVICE_PORTAL is
#: excluded on purpose (Gate 0): its native platform ids are not in
#: :class:`Piattaforma`.
_SUPPORTED_SURFACES = frozenset({Surface.ORDINARY_DATA, Surface.TRANSPARENCY})

#: Built once. ``build_recognition_registry`` registers 7 native plugins + 4
#: bridges; rebuilding per call would repeat that work on every recognition.
_REGISTRY = build_recognition_registry()


def _prova_da_evidence(match: RecognitionMatch) -> str | None:
    """Synthesise the legacy ``prova`` string from the winning evidence.

    Native plugins carry :class:`FingerprintEvidence`, not the classifier's
    prose ``prova``. The first matched signal is the honest stand-in: prefer its
    human ``description``, fall back to ``key: observed``. ``None`` only when no
    signal matched (a miss never reaches here).
    """
    for evidence in match.result.evidence:
        if not evidence.matched:
            continue
        if evidence.description:
            return evidence.description
        if evidence.observed is not None:
            return f"{evidence.key}: {evidence.observed}"
        return evidence.key
    return None


def firma_da_registro(
    *,
    headers: dict[str, str],
    html: str,
    surface: Surface,
    source_id: str,
    entrypoint_url: str,
    expected_platform: str | None = None,
) -> Firma:
    """Drop-in replacement for ``firma_da_risposta`` on BASE/AT via the registry.

    ``includi_at`` is not a parameter: the surface encodes it (the bridge runs
    ``classifica_risposta`` with ``includi_at=False`` on ORDINARY_DATA and
    ``True`` on TRANSPARENCY). A registry miss (``None``) maps to the legacy
    sentinel ``Firma(Piattaforma.IGNOTA, None)``.

    Raises ``ValueError`` for ``Surface.SERVICE_PORTAL``: its native platform ids
    are not representable in :class:`Piattaforma` yet (Gate 0). The caller must
    not silently receive ``IGNOTA`` for a portal the plugin actually recognised.
    """
    if surface not in _SUPPORTED_SURFACES:
        raise ValueError(
            f"firma_da_registro does not support {surface!r}: the legacy Firma "
            "vocabulary cannot represent its native platform ids (Gate 0)"
        )

    observation = RecognitionObservation(
        source_id=source_id,
        surface=surface,
        entrypoint_url=entrypoint_url,
        http_status=200,
        headers=headers,
        body=html,
        expected_platform=expected_platform,
    )
    match = _REGISTRY.recognize(observation)
    if match is None or match.result.platform_id is None:
        return Firma(Piattaforma.IGNOTA, None)

    try:
        piattaforma = Piattaforma(match.result.platform_id)
    except ValueError:
        # Defensive only: on BASE/AT every native/bridge id is a valid enum
        # member, so this fires on genuinely corrupt output, never as an SP
        # compatibility policy (that path is refused above). Degrade to IGNOTA
        # and leave a trace rather than crash the sweep.
        logger.warning(
            "recognition adapter: platform id %r on %s is not a Piattaforma member",
            match.result.platform_id,
            surface.value,
        )
        return Firma(Piattaforma.IGNOTA, None)

    return Firma(piattaforma, _prova_da_evidence(match))
