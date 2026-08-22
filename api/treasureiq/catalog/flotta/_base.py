"""Shared mechanics for the fleet connectors.

Every concrete unit is one ``(platform × surface)`` pair — its own name, its own
version, registered on its own.  The ``retrieve`` body is shared because it only
projects the already-acquired ``esito`` (never a re-fetch); the identity that
travels into the catalog batch and, later, into the recognition fingerprint is
``ConnectorRef(name, version)``, stamped per unit.

Two surface bases fix the surface and its capabilities; the leaf classes fix only
``platform_id``, ``name`` and ``version`` — so bumping one platform's version is a
one-line edit in that platform's own module, isolated from the others (I2).
"""

from __future__ import annotations

from treasureiq.catalog.connectors import ConnectorResult
from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.data_contracts import ConnectorRef, DataRequest, TransportMeta
from treasureiq.catalog.flotta import _projection
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore


class _FlottaConnettore:
    """Common acquisition mechanics; subclasses fix surface, platform, identity."""

    platform_id: str = ""
    surface: Surface
    capabilities: frozenset[str] = frozenset()
    name: str = ""
    version: str = ""

    def supports(self, request: DataRequest, *, platform_id: str) -> bool:
        return (
            platform_id == self.platform_id
            and request.surface is self.surface
            and request.capability in self.capabilities
        )

    def retrieve(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> ConnectorResult:
        if request.source_id != mappa.codice_istat:
            raise ValueError("request.source_id does not match the measured source")

        mode = _projection.access_mode(request.surface, request.capability, esito)
        record_dicts = _projection.records(request.surface, request.capability, esito)[
            : request.limits.max_records
        ]
        fresh = _projection.freshness(
            esito.letto_il if esito else "", request.freshness.max_age_seconds
        )
        return ConnectorResult(
            request_id=request.request_id,
            source_id=request.source_id,
            status=_projection.status(mode, record_dicts, fresh),
            access_mode=mode,
            records=tuple(record_dicts),
            evidence=_projection.evidence(record_dicts),
            freshness=fresh,
            limitations=self._limitations(request),
            transport=TransportMeta(from_cache=True),
            connector=ConnectorRef(name=self.name, version=self.version),
        )

    def _limitations(self, request: DataRequest) -> tuple[str, ...]:
        return ()


class FlottaBaseConnettore(_FlottaConnettore):
    """BASE surface: the office directory and its contact details."""

    surface = Surface.ORDINARY_DATA
    capabilities = frozenset({"offices", "contacts"})

    def _limitations(self, request: DataRequest) -> tuple[str, ...]:
        if request.capability == "contacts":
            return (
                "I recapiti sono disponibili solo se pubblicati sulla scheda dell'ufficio.",
            )
        return ()


class FlottaTrasparenzaConnettore(_FlottaConnettore):
    """AT surface: the transparency index only; PDF reading is out of scope."""

    surface = Surface.TRANSPARENCY
    capabilities = frozenset({"transparency"})

    def _limitations(self, request: DataRequest) -> tuple[str, ...]:
        return ("L'analisi dei PDF non fa parte di questo connettore.",)
