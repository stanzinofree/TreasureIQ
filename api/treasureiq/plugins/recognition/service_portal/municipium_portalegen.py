"""Native SERVICE_PORTAL recognition for the Municipium "portale genitori".

Unlike the two AT plugins, this is a greenfield fingerprint: the legacy
classifier has no ``portalegen`` signature, so the v1 bridge is blind to this
surface. Captured live from Almese's school-services portal
(``serviziscolastici.comune.almese.to.it/portalegen``, Microsoft-IIS/ASP.NET),
which serves the AGID ``bootstrap-italia`` UI under the Municipium theme.

Recognition requires BOTH signals together, never either alone:

* ``container-municipium-agid`` — the Municipium AGID theme container. On its
  own it also appears on the BASE Municipium site, so it cannot identify the
  service portal by itself.
* a ``/portalegen/plugins`` asset root — the portal application's own static
  tree. On its own it is just a path that could survive a migration.

Together they are an involuntary, portal-specific fingerprint.
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


_BODY_LIMIT = 40_000
# The v1 bridge is not silent on this page: the word "municipium" inside the
# ``container-municipium-agid`` class trips its ``\bmunicipium\b`` host rule, so
# the bridge mis-claims the generic BASE platform ``municipium`` at the
# host_prodotto score 0.995. We mirror exactly that score so the registry's
# native-beats-wildcard tie-break — not a bigger number — hands this surface
# the correct, specific identity ``municipium_portalegen``. (host_prodotto:
# ``ingest.piattaforma._score(100, "host_prodotto") / 100`` = 0.995.)
_SCORE = 0.995

#: Municipium AGID theme container. Necessary but not sufficient: also present
#: on the BASE Municipium site, so it never wins alone.
_MUNICIPIUM_AGID = re.compile(r"container-municipium-agid", re.I)

#: Static asset root of the portalegen application (``/portalegen/plugins`` and
#: ``/portalegen/plugins2``). The functional signature of the service portal.
_PORTALEGEN_ASSET = re.compile(r"/portalegen/plugins2?/", re.I)


class MunicipiumPortalegenRecognitionPlugin:
    """Recognize the Municipium portalegen SP without network or legacy imports."""

    manifest = RecognitionPluginManifest(
        plugin_id="municipium_portalegen_sp",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="municipium-portalegen-sp-v1",
        surface=Surface.SERVICE_PORTAL,
        platforms=("municipium_portalegen",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        body = observation.body[:_BODY_LIMIT]

        theme = _MUNICIPIUM_AGID.search(body)
        asset = _PORTALEGEN_ASSET.search(body)
        if not (theme and asset):
            return RecognitionPluginResult(recognition_score=0.0)

        evidence = (
            FingerprintEvidence(
                key="municipium_agid",
                description=f"theme container: {theme.group(0)}",
                matched=True,
                weight=_SCORE,
                observed=theme.group(0),
            ),
            FingerprintEvidence(
                key="portalegen_asset",
                description=f"asset root: {asset.group(0)}",
                matched=True,
                weight=_SCORE,
                observed=asset.group(0),
            ),
        )
        fingerprint = "sha256:" + hashlib.sha256(
            f"municipium_agid:{theme.group(0)}|portalegen_asset:{asset.group(0)}".encode()
        ).hexdigest()
        return RecognitionPluginResult(
            platform_id="municipium_portalegen",
            recognition_score=_SCORE,
            confidence=RecognitionConfidence.HIGH,
            fingerprint=fingerprint,
            evidence=evidence,
        )


PLUGIN = MunicipiumPortalegenRecognitionPlugin()
MUNICIPIUM_PORTALEGEN_RECOGNITION_PLUGIN = PLUGIN
