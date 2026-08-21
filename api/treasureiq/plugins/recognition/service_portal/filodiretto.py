"""Native SERVICE_PORTAL recognition for the Siscom "Filodiretto" portal.

Greenfield fingerprint, like ``municipium_portalegen`` — but the bridge is
genuinely blind here, not merely mis-firing. Verified empirically: over a page
carrying the markers below the v1 ``classifica_risposta`` returns ``ignota``
with no signature scored (the ``_PEOPLEWEB`` Siscom rule wants a Windows-style
``assets\\bootstrap-italia`` path or a ``bootstrap-italia-comuni*.css``, neither
of which this portal emits). So there is no coincidental score to mirror: the
native plugin simply fills the gap and wins outright over the empty bridge.

Captured live from Sauze d'Oulx's Filodiretto portal
(``servizidigitali.comune.sauzedoulx.to.it/servizi/filodiretto2/ProcedimentiClient.Aspx``,
Microsoft-IIS/ASP.NET WebForms serving the AGID ``bootstrap-italia`` UI). The
same ``/servizi/filodiretto2/ProcedimentiClient.Aspx`` route recurs verbatim
across every sampled installation (Cisterna, Racale, Arquata Scrivia, ...),
which makes the route — not the ambiguous word "filodiretto" — the anchor.

Recognition requires BOTH signals together, never either alone:

* ``/servizi/filodiretto2/`` — the versioned product application route. The
  bare word "filodiretto" ("direct line") is common Italian civic wording and
  is the discovery provider hint, so it cannot identify the product by itself.
* ``siscomJS.js`` — the Siscom vendor framework asset. Confirms the vendor
  behind the route (Siscom, the same house as one of the two ``peopleweb``
  products; see the OpenWeb+Siscom split).

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
# Greenfield: the v1 bridge scores this page at 0 (``ignota``), so no tie-break
# is involved — any positive score wins. We pick a definitive HIGH score at the
# host_prodotto tier, matching the sibling SP product plugin (portalegen):
# ``ingest.piattaforma._score(100, "host_prodotto") / 100`` = 0.995.
_SCORE = 0.995

#: Versioned product application route. Recurs verbatim across every sampled
#: Filodiretto installation. Necessary but not sufficient: the bare word
#: "filodiretto" is generic civic wording and the discovery provider hint.
_FILODIRETTO_ROUTE = re.compile(r"/servizi/filodiretto2/", re.I)

#: Siscom vendor framework asset. Confirms the product behind the route.
_SISCOM_ASSET = re.compile(r"siscomJS\.js", re.I)


class FilodirettoRecognitionPlugin:
    """Recognize the Siscom Filodiretto SP without network or legacy imports."""

    manifest = RecognitionPluginManifest(
        plugin_id="filodiretto_sp",
        version="1.0.0",
        contract_version="recognition.v1",
        fingerprint_version="filodiretto-sp-v1",
        surface=Surface.SERVICE_PORTAL,
        platforms=("filodiretto",),
    )

    def recognize(self, observation: RecognitionObservation) -> RecognitionPluginResult:
        # The route appears both in the entrypoint URL and inside the body
        # (form action, resource paths); search both so a captured surface
        # missing one still matches.
        haystack = f"{observation.entrypoint_url or ''}\n{observation.body[:_BODY_LIMIT]}"

        route = _FILODIRETTO_ROUTE.search(haystack)
        asset = _SISCOM_ASSET.search(haystack)
        if not (route and asset):
            return RecognitionPluginResult(recognition_score=0.0)

        evidence = (
            FingerprintEvidence(
                key="filodiretto_route",
                description=f"product route: {route.group(0)}",
                matched=True,
                weight=_SCORE,
                observed=route.group(0),
            ),
            FingerprintEvidence(
                key="siscom_asset",
                description=f"vendor asset: {asset.group(0)}",
                matched=True,
                weight=_SCORE,
                observed=asset.group(0),
            ),
        )
        fingerprint = "sha256:" + hashlib.sha256(
            f"filodiretto_route:{route.group(0)}|siscom_asset:{asset.group(0)}".encode()
        ).hexdigest()
        return RecognitionPluginResult(
            platform_id="filodiretto",
            recognition_score=_SCORE,
            confidence=RecognitionConfidence.HIGH,
            fingerprint=fingerprint,
            evidence=evidence,
        )


PLUGIN = FilodirettoRecognitionPlugin()
FILODIRETTO_RECOGNITION_PLUGIN = PLUGIN
