"""Bridge from the v0 WordPress-AgID connector to the v1 data contract.

The adapter does not decide what the user meant and does not call Ollama.  It
only maps an already measured source and an already retrieved connector result
to one deterministic :class:`DataBatch` for one capability.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from treasureiq.catalog.contracts import AccessMode, FreshnessStatus, Surface
from treasureiq.catalog.data_contracts import (
    ConnectorRef,
    DataBatch,
    DataRequest,
    DataStatus,
    EvidenceRef,
    Freshness,
    TransportMeta,
)
from treasureiq.catalog.plugins import CapabilityManifest, PluginManifest
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore

WORDPRESS_AGID_VERSION = "1"
WORDPRESS_AGID_MANIFEST = PluginManifest(
    plugin_id="wordpress_agid",
    version=WORDPRESS_AGID_VERSION,
    contract_version="catalog.v1",
    platforms=("wordpress_agid",),
    capabilities=(
        CapabilityManifest(surface=Surface.ORDINARY_DATA, capability="services", priority=10),
        CapabilityManifest(surface=Surface.ORDINARY_DATA, capability="offices", priority=20),
        CapabilityManifest(surface=Surface.ORDINARY_DATA, capability="contacts", priority=30),
        CapabilityManifest(surface=Surface.TRANSPARENCY, capability="transparency", priority=40),
    ),
)


class WordPressAgidAdapter:
    """Produce deterministic batches from the existing WordPress adapter."""

    name = "wordpress_agid"
    version = WORDPRESS_AGID_VERSION
    manifest = WORDPRESS_AGID_MANIFEST

    def supports(self, platform_id: str, surface: str) -> bool:
        return platform_id == self.name and self.manifest.supports(surface=surface)

    def read(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
        records: tuple[dict[str, Any], ...] = (),
    ) -> DataBatch:
        if request.source_id != mappa.codice_istat:
            raise ValueError("request.source_id does not match the measured source")

        mode = self._access_mode(request.surface, request.capability, mappa, esito)
        records = self._records(request.surface, request.capability, mappa, esito)
        freshness = self._freshness(mappa.sondato_il, request.freshness.max_age_seconds)
        status = self._status(mode, records, freshness)
        evidence = tuple(
            EvidenceRef(evidence_id=str(record["url"]), field="url")
            for record in records
            if record.get("url")
        )

        limitations: list[str] = []
        if request.capability == "contacts":
            limitations.append("I recapiti sono disponibili solo se pubblicati sulla scheda dell'ufficio.")
        if request.surface is Surface.TRANSPARENCY:
            limitations.append("L'analisi dei PDF non fa parte di questo adapter.")

        return DataBatch(
            request_id=request.request_id,
            status=status,
            access_mode=mode,
            source_id=request.source_id,
            surface=request.surface,
            capability=request.capability,
            records=tuple(records[: request.limits.max_records]),
            evidence=evidence[: request.limits.max_records],
            freshness=freshness,
            limitations=tuple(limitations),
            transport=TransportMeta(from_cache=True),
            connector=ConnectorRef(name=self.name, version=WORDPRESS_AGID_VERSION),
        )

    @staticmethod
    def _access_mode(
        surface: Surface,
        capability: str,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> AccessMode:
        if surface is Surface.ORDINARY_DATA:
            if capability == "services":
                return AccessMode.DIRECT if mappa.servizi.esposto else AccessMode.UNAVAILABLE
            if capability == "offices":
                return AccessMode.DIRECT if mappa.uffici.esposto else AccessMode.UNAVAILABLE
            if capability == "contacts":
                if not mappa.uffici.esposto:
                    return AccessMode.UNAVAILABLE
                return AccessMode.DIRECT if mappa.contatti_via == "REST" else AccessMode.MEDIATED
            return AccessMode.UNAVAILABLE

        if capability != "transparency" or esito is None or esito.amministrazione_trasparente is None:
            return AccessMode.UNAVAILABLE
        return (
            AccessMode.DIRECT
            if mappa.amministrazione_trasparente_via == "REST"
            else AccessMode.MEDIATED
        )

    @staticmethod
    def _records(
        surface: Surface,
        capability: str,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> list[dict[str, Any]]:
        if surface is Surface.ORDINARY_DATA and capability == "services":
            return [category.model_dump(mode="json") for category in mappa.servizi.categorie]
        if surface is Surface.ORDINARY_DATA and capability == "offices":
            return [office.model_dump(mode="json") for office in (esito.uffici if esito else [])]
        if surface is Surface.ORDINARY_DATA and capability == "contacts":
            return [
                {
                    "nome": office.nome,
                    "url": office.url,
                    "telefoni": office.telefoni,
                    "email": office.email,
                    "pec": office.pec,
                }
                for office in (esito.uffici if esito else [])
                if office.telefoni or office.email or office.pec
            ]
        if surface is Surface.TRANSPARENCY and capability == "transparency":
            at = esito.amministrazione_trasparente if esito else None
            return [at.model_dump(mode="json")] if at else []
        return []

    @staticmethod
    def _freshness(measured_at: str, max_age_seconds: int) -> Freshness:
        try:
            retrieved_at = datetime.fromisoformat(measured_at)
            if retrieved_at.tzinfo is None:
                retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
            age = max(0, int((datetime.now(timezone.utc) - retrieved_at).total_seconds()))
        except (TypeError, ValueError):
            return Freshness(status=FreshnessStatus.INVALID)
        status = FreshnessStatus.FRESH if age <= max_age_seconds else FreshnessStatus.STALE
        return Freshness(status=status, retrieved_at=retrieved_at, source_age_seconds=age)

    @staticmethod
    def _status(
        mode: AccessMode,
        records: list[dict[str, Any]],
        freshness: Freshness,
    ) -> DataStatus:
        if mode is AccessMode.UNAVAILABLE:
            return DataStatus.NOT_SUPPORTED
        if freshness.status in (FreshnessStatus.STALE, FreshnessStatus.INVALID):
            return DataStatus.STALE
        return DataStatus.FULFILLED if records else DataStatus.EMPTY
