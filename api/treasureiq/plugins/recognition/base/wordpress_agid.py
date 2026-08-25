"""Native BASE recognition for the WordPress family used by the connector.

This plugin recognizes evidence that the legacy BASE classifier already
considers WordPress evidence, plus one greenfield marker captured live from
Arona's ``/wp-json/wp/v2/types`` payload: the AgID service CPT declaration
(``"slug":"servizio"`` together with ``"rest_base":"servizi"``) — the exact
surface the acquisition connector queries.  ``wordpress_agid`` is the
acquisition connector and is deliberately not returned as a platform identity:
the observed platform remains ``wordpress_generico`` (promoting a more
specific identity, e.g. a Design Comuni theme id, needs a theme marker that
the captured fixtures do not contain).

The same Design Comuni theme hides TWO REST dialects behind an identical
``/wp/v2/servizi`` collection, so the theme name alone can never separate
them; only the observed item shape can:

* dialect A (standard WP REST controller): items carry ``"id"`` and
  ``"title":{"rendered":…}`` — what the acquisition connector consumes;
* dialect B (custom REST controller, captured live from Albaredo d'Adige):
  items carry ``"ID"``/``"post_title"`` with direct AgID fields and no
  ``link``/``title.rendered`` — the standard connector reads it as an empty
  result (a false empty, not a real one).
"""

from __future__ import annotations

import hashlib
import re

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import FingerprintEvidence, RecognitionConfidence
from treasureiq.catalog.recognition_plugins import (
    RecognitionObservation,
    RecognitionPluginManifest,
    RecognitionPluginResult,
)


_HEAD_LIMIT = 8_192
_ASSET_LIMIT = 40_000
_DEFINITIVE = 100.0
_EURISTIC = 50.0
_RANK_GENERATOR = 2
_RANK_LINK_API = 3
# Greenfield rank: the CPT declaration has no legacy counterpart, so this rank
# mirrors no bridge table.  It sits below ``link_wp_api`` on purpose: when both
# fire the REST-link signature still wins, preserving score parity with the v1
# bridge on the shared home-page fixtures.
_RANK_CPT_SERVIZI = 4
# Greenfield ranks for the two REST item-shape dialects (no legacy
# counterpart): below the CPT declaration, above the heuristic asset match.
_RANK_REST_ITEM_STANDARD = 5
_RANK_REST_ITEM_CUSTOM = 6
_RANK_ASSET = 7
_EPSILON = 0.1

_META_GENERATOR = re.compile(
    r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"'](?P<v>[^\"']{1,120})",
    re.I,
)
_LINK_WP_API = re.compile(r"<link[^>]+https://api\.w\.org/", re.I)
_WP_ASSET = re.compile(r"/wp-(?:content|includes)/", re.I)
_WORDPRESS = re.compile(r"\bWordPress\b", re.I)

#: The AgID service CPT as the WP REST types payload declares it (captured live
#: from Arona, ``tests/fixtures/wordpress_agid/arona_types.json``).  Both
#: signals are required together, never either alone: a page merely *linking*
#: ``/servizi/`` or naming a "servizio" is not a CPT declaration.
_CPT_SERVIZIO_SLUG = re.compile(r'"slug"\s*:\s*"servizio"')
_CPT_SERVIZI_REST_BASE = re.compile(r'"rest_base"\s*:\s*"servizi"')

#: Dialect A — the standard WP REST item shape the acquisition connector
#: consumes (captured live from Arona: ``arona_carta_identita.json``).  Both
#: signals required together: a bare ``"id"`` occurs in any JSON.
_REST_ITEM_ID = re.compile(r'"id"\s*:\s*\d')
_REST_ITEM_TITLE_RENDERED = re.compile(r'"title"\s*:\s*\{\s*"rendered"')
#: Dialect B — the custom REST controller of the same theme (captured live
#: from Albaredo d'Adige: ``albaredo_dialettoB_raw.json``): uppercase
#: ``"ID"``/``"post_title"`` anchored to the service CPT.  The standard
#: connector cannot read this shape — the payload is data, not emptiness.
_REST_ITEM_ID_UPPER = re.compile(r'"ID"\s*:\s*\d')
_REST_ITEM_POST_TITLE = re.compile(r'"post_title"\s*:')
_REST_ITEM_POST_TYPE_SERVIZIO = re.compile(r'"post_type"\s*:\s*"servizio"')


def _score(raw: float, rank: int) -> float:
    return (raw - rank * _EPSILON) / 100.0


def _confidence(score: float) -> RecognitionConfidence:
    if score >= 0.75:
        return RecognitionConfidence.HIGH
    if score >= 0.25:
        return RecognitionConfidence.MEDIUM
    if score > 0.0:
        return RecognitionConfidence.LOW
    return RecognitionConfidence.UNKNOWN


class WordPressAgidRecognitionPlugin:
    """Recognize WordPress BASE evidence without network or legacy imports."""

    manifest = RecognitionPluginManifest(
        plugin_id="wordpress_agid_base",
        version="1.1.0",
        contract_version="recognition.v1",
        fingerprint_version="wordpress-base-v2",
        surface=Surface.ORDINARY_DATA,
        platforms=("wordpress_generico",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        head = observation.body[:_HEAD_LIMIT]
        body = observation.body[:_ASSET_LIMIT]
        matches: list[tuple[str, str, float]] = []

        generator = _META_GENERATOR.search(head)
        if generator and _WORDPRESS.search(generator.group("v")):
            value = generator.group("v")
            matches.append(("generator", f"generator: {value}", _score(_EURISTIC, _RANK_GENERATOR)))

        if _LINK_WP_API.search(head):
            matches.append(("link_wp_api", "link rel=https://api.w.org/", _score(_DEFINITIVE, _RANK_LINK_API)))

        asset = _WP_ASSET.search(body)
        if asset:
            matches.append(("asset", f"asset: {asset.group(0)}", _score(_EURISTIC, _RANK_ASSET)))

        slug = _CPT_SERVIZIO_SLUG.search(body)
        rest_base = _CPT_SERVIZI_REST_BASE.search(body)
        if slug and rest_base:
            matches.append(
                (
                    "cpt_servizi",
                    f"CPT servizio esposto: {slug.group(0)} + {rest_base.group(0)}",
                    _score(_DEFINITIVE, _RANK_CPT_SERVIZI),
                )
            )

        if _REST_ITEM_ID.search(body) and _REST_ITEM_TITLE_RENDERED.search(body):
            matches.append(
                (
                    "rest_item_standard",
                    'dialetto A: item REST standard ("id" + "title":{"rendered"})',
                    _score(_DEFINITIVE, _RANK_REST_ITEM_STANDARD),
                )
            )
        if (
            _REST_ITEM_ID_UPPER.search(body)
            and _REST_ITEM_POST_TITLE.search(body)
            and _REST_ITEM_POST_TYPE_SERVIZIO.search(body)
        ):
            matches.append(
                (
                    "rest_item_custom",
                    'dialetto B: item REST custom ("ID"/"post_title", post_type servizio)',
                    _score(_DEFINITIVE, _RANK_REST_ITEM_CUSTOM),
                )
            )

        if not matches:
            return RecognitionPluginResult(recognition_score=0.0)

        winner = max(matches, key=lambda item: item[2])
        evidence = tuple(
            FingerprintEvidence(
                key=key,
                description=description,
                matched=key == winner[0],
                weight=score,
                observed=description,
            )
            for key, description, score in matches
        )
        fingerprint_payload = "|".join(f"{key}:{description}" for key, description, _ in matches)
        fingerprint = "sha256:" + hashlib.sha256(fingerprint_payload.encode()).hexdigest()
        return RecognitionPluginResult(
            platform_id="wordpress_generico",
            recognition_score=winner[2],
            confidence=_confidence(winner[2]),
            fingerprint=fingerprint,
            evidence=evidence,
        )


PLUGIN = WordPressAgidRecognitionPlugin()
