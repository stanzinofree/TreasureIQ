"""eGov/HGATE connectors: transparency index only (PDF reading out of scope).

``leggi_egov`` fills ``esito.amministrazione_trasparente``; these units project
that index into the catalog TRANSPARENCY surface. Versioned on their own (I2).
"""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaTrasparenzaConnettore

EGOV_TRASPARENZA_VERSION = "1.0.0"
HGATE_TRASPARENZA_VERSION = "1.0.0"


class EGovTrasparenzaConnettore(FlottaTrasparenzaConnettore):
    platform_id = "egov"
    name = "egov.trasparenza"
    version = EGOV_TRASPARENZA_VERSION


class HGateTrasparenzaConnettore(FlottaTrasparenzaConnettore):
    platform_id = "hgate"
    name = "hgate.trasparenza"
    version = HGATE_TRASPARENZA_VERSION
