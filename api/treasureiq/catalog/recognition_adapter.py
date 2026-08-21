"""Legacy-shaped bridge from the production recognition registry.

The runtime selects a connector from a :class:`Firma` (``piattaforma`` enum +
verbatim ``prova``). The recognition registry instead returns a
:class:`RecognitionMatch` whose ``platform_id`` is a string. This adapter is the
one seam that maps the registry's answer back onto the legacy ``Firma`` so the
BASE dispatch (``connettore``) and the AT confirmation keep working — now driven
by the 7 native plugins + Passo C suppression rather than by ``classifica_risposta``
directly.

``firma_da_registro`` is deliberately **BASE and AT only** (Gate 0 in the T2
planning doc). The native SP plugins emit ``municipium_portalegen`` /
``filodiretto``, which are not members of :class:`Piattaforma`; wiring
``SERVICE_PORTAL`` through the legacy vocabulary would silently collapse those
identities to ``IGNOTA``. So that function refuses ``Surface.SERVICE_PORTAL``
outright, and the SP surface is served by a separate seam,
``riconosci_service_portal``, which returns the native ``platform_id`` string
directly (:class:`RiconoscimentoSP`) and never goes through ``Firma``.

``classifica_risposta`` is untouched: the registry wraps it via the legacy
bridge, it does not replace it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import FingerprintEvidence
from treasureiq.catalog.recognition_bridge import (
    build_recognition_registry,
    build_service_portal_registry,
)
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

#: SERVICE_PORTAL registry: the native SP plugins only, no bridge. Built once,
#: same reasoning as ``_REGISTRY``.
_SP_REGISTRY = build_service_portal_registry()


def _prima_prova(evidence: tuple[FingerprintEvidence, ...]) -> str | None:
    """First matched signal as a human ``prova`` string, or ``None``.

    Native plugins carry :class:`FingerprintEvidence`, not the classifier's
    prose ``prova``. The first matched signal is the honest stand-in: prefer its
    human ``description``, fall back to ``key: observed``.
    """
    for item in evidence:
        if not item.matched:
            continue
        if item.description:
            return item.description
        if item.observed is not None:
            return f"{item.key}: {item.observed}"
        return item.key
    return None


def _prova_da_evidence(match: RecognitionMatch) -> str | None:
    """Legacy ``prova`` from the winning match (a miss never reaches here)."""
    return _prima_prova(match.result.evidence)


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


@dataclass(frozen=True)
class RiconoscimentoSP:
    """SERVICE_PORTAL recognition outcome, outside the ``Firma``/``Piattaforma``
    vocabulary.

    ``platform_id`` is the native id string (``"municipium_portalegen"`` /
    ``"filodiretto"``) or ``None`` on a miss. Carries the native ``fingerprint``
    and ``evidence`` so a caller can persist the involuntary signature, and
    ``prova`` — the first matched signal — as a human stand-in.
    """

    platform_id: str | None
    fingerprint: str | None
    recognition_score: float
    evidence: tuple[FingerprintEvidence, ...]
    prova: str | None


def riconosci_service_portal(
    *,
    headers: dict[str, str],
    html: str,
    source_id: str,
    entrypoint_url: str,
) -> RiconoscimentoSP:
    """Recognise a SERVICE_PORTAL through the native-only SP registry.

    Separate from ``firma_da_registro`` on purpose: the SP native ids are not
    ``Piattaforma`` members, and the SP registry carries no legacy bridge, so no
    BASE id (e.g. ``municipium``) can leak onto this surface. A miss is an honest
    ``RiconoscimentoSP(None, ...)`` — a greenfield no-match is not a denial, so
    the caller keeps trusting the persisted provider hint on ``None``.

    Recognition is deliberately independent of any expected/persisted platform:
    passing it as a registry ``hint`` would filter out every plugin that does not
    already claim it, so a page that drifted to a *different* vendor could never
    be recognised. The caller compares the returned ``platform_id`` against the
    persisted hint to detect drift.
    """
    observation = RecognitionObservation(
        source_id=source_id,
        surface=Surface.SERVICE_PORTAL,
        entrypoint_url=entrypoint_url,
        http_status=200,
        headers=headers,
        body=html,
    )
    match = _SP_REGISTRY.recognize(observation)
    if match is None or match.result.platform_id is None:
        return RiconoscimentoSP(None, None, 0.0, (), None)

    result = match.result
    return RiconoscimentoSP(
        platform_id=result.platform_id,
        fingerprint=result.fingerprint,
        recognition_score=result.recognition_score,
        evidence=result.evidence,
        prova=_prima_prova(result.evidence),
    )
