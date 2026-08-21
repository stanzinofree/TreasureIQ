"""Core-owned dispatch for recognition plugins.

The registry is the seam the doctrine calls "core": it never fingerprints. It
routes one :class:`RecognitionObservation` to the plugins that declared the
matching surface, runs them without network I/O, and lets the strongest score
win. Native plugins (an explicit ``platforms`` tuple) beat the wildcard v1
bridge on a tie, which is exactly how a family stops being served by the
legacy bridge the day its plugin lands.

Turning a plugin result into a persisted :class:`RecognitionResult` — adding
``source_id``, versions, timestamp and the keep/confirm/rediscover verdict —
also lives here, not in any plugin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from treasureiq.catalog.recognition import (
    RecognitionAction,
    RecognitionResult,
    ResweepPolicy,
    action_for_recognition,
)
from treasureiq.catalog.recognition_plugins import (
    RecognitionObservation,
    RecognitionPlugin,
    RecognitionPluginManifest,
    RecognitionPluginResult,
)


@dataclass(frozen=True)
class RecognitionMatch:
    """The winning plugin's manifest paired with its raw result."""

    manifest: RecognitionPluginManifest
    result: RecognitionPluginResult


def _is_native(manifest: RecognitionPluginManifest) -> bool:
    return "*" not in manifest.platforms


class RecognitionRegistry:
    """In-memory registry keyed by ``(plugin_id, surface)`` with strict add."""

    def __init__(self) -> None:
        self._plugins: list[RecognitionPlugin] = []

    def register(self, plugin: RecognitionPlugin) -> None:
        key = (plugin.manifest.plugin_id, plugin.manifest.surface)
        if any(
            (p.manifest.plugin_id, p.manifest.surface) == key for p in self._plugins
        ):
            raise ValueError(f"recognition plugin already registered: {key}")
        self._plugins.append(plugin)

    def _candidates(self, observation: RecognitionObservation) -> list[RecognitionPlugin]:
        hint = observation.expected_platform or observation.base_platform_hint
        chosen: list[RecognitionPlugin] = []
        for plugin in self._plugins:
            if plugin.manifest.surface is not observation.surface:
                continue
            platforms = plugin.manifest.platforms
            # A hint narrows to plugins that claim it; the wildcard bridge always
            # stays in the race so an unknown platform is never dropped silently.
            if "*" in platforms or hint is None or hint in platforms:
                chosen.append(plugin)
        return chosen

    def recognize(self, observation: RecognitionObservation) -> RecognitionMatch | None:
        """Return the highest-scoring recognition for this surface, or ``None``.

        A score of ``0.0`` is a miss for every plugin (native plugins and the
        suppressed bridge both return it), so an all-zero surface recognises
        nothing: return ``None`` rather than attributing an empty result to the
        first native plugin the tie-break happened to reach. Callers treat
        ``None`` as manual review — the same verdict an empty platform yields.
        """
        best: RecognitionMatch | None = None
        best_native = False
        for plugin in self._candidates(observation):
            result = plugin.recognize(observation)
            native = _is_native(plugin.manifest)
            if best is None:
                best, best_native = RecognitionMatch(plugin.manifest, result), native
                continue
            higher = result.recognition_score > best.result.recognition_score
            tie = result.recognition_score == best.result.recognition_score
            if higher or (tie and native and not best_native):
                best, best_native = RecognitionMatch(plugin.manifest, result), native
        if best is None or best.result.recognition_score <= 0.0:
            return None
        return best

    def names(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (p.manifest.plugin_id, p.manifest.surface.value) for p in self._plugins
        )


def build_recognition_result(
    observation: RecognitionObservation,
    match: RecognitionMatch,
    *,
    checked_at: datetime,
    policy: ResweepPolicy | None = None,
    fingerprint_changed: bool = False,
    connector_major_changed: bool = False,
    connector_minor_changed: bool = False,
    coverage_score: float | None = None,
    source_health: bool | None = None,
    failure_reason: str | None = None,
) -> RecognitionResult:
    """Wrap a plugin result into the persisted record the core owns.

    The change-detection flags default to "nothing changed": diffing this run
    against prior state is the caller's job, kept out of the seam so the
    registry stays a pure router.
    """
    resolved = policy or ResweepPolicy()
    action = action_for_recognition(
        score=match.result.recognition_score,
        policy=resolved,
        fingerprint_changed=fingerprint_changed,
        connector_major_changed=connector_major_changed,
        connector_minor_changed=connector_minor_changed,
    )
    return RecognitionResult(
        source_id=observation.source_id,
        surface=observation.surface,
        platform_id=match.result.platform_id,
        connector_id=match.manifest.plugin_id,
        connector_version=match.manifest.version,
        fingerprint_version=match.manifest.fingerprint_version,
        fingerprint=match.result.fingerprint,
        recognition_score=match.result.recognition_score,
        coverage_score=coverage_score,
        source_health=source_health,
        failure_reason=failure_reason,
        confidence=match.result.confidence,
        evidence=match.result.evidence,
        checked_at=checked_at,
        action=action if match.result.platform_id else RecognitionAction.MANUAL_REVIEW,
    )
