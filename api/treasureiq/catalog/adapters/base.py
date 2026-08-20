"""Universal adapter seam for catalog data retrieval."""

from __future__ import annotations

from typing import Protocol

from treasureiq.catalog.data_contracts import DataBatch, DataRequest
from treasureiq.connettore import EsitoConnettore
from treasureiq.mappa_connettore import MappaConnettore


class CatalogAdapter(Protocol):
    name: str
    version: str

    def supports(self, platform_id: str, surface: str) -> bool:
        """Return whether this adapter can read the measured platform."""

    def read(
        self,
        request: DataRequest,
        *,
        mappa: MappaConnettore,
        esito: EsitoConnettore | None,
    ) -> DataBatch:
        """Read one capability and return the closed v1 batch contract."""
