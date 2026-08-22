"""Fleet connectors: one independent, versioned unit per (platform × surface).

Each concrete connector covers exactly one platform and one surface (BASE or AT)
and carries its own name and version, so writing or evolving one does not ripple
into the others (I2).  They all project the same v0 ``EsitoConnettore`` through a
shared pure helper; the SERVICE_PORTAL surface is deliberately absent until its
executor is wired (slice 3E).

``flotta_connectors()`` returns the units in registration order and
``flotta_adapter()`` returns the single gate adapter; the composition roots use
both to place the fleet ahead of the wildcard scrape fallback.
"""

from __future__ import annotations

from treasureiq.catalog.connectors import SourceConnector
from treasureiq.catalog.flotta._adapter import (
    FLOTTA_ADAPTER_VERSION,
    FLOTTA_MANIFEST,
    FLOTTA_PLATFORMS,
    FlottaAdapter,
)
from treasureiq.catalog.flotta.comweb.base import ComWebBaseConnettore
from treasureiq.catalog.flotta.comweb.trasparenza import ComWebTrasparenzaConnettore
from treasureiq.catalog.flotta.egov.base import (
    EGovBaseConnettore,
    HGateBaseConnettore,
)
from treasureiq.catalog.flotta.egov.trasparenza import (
    EGovTrasparenzaConnettore,
    HGateTrasparenzaConnettore,
)
from treasureiq.catalog.flotta.municipium.base import MunicipiumBaseConnettore
from treasureiq.catalog.flotta.municipium.trasparenza import (
    MunicipiumTrasparenzaConnettore,
)
from treasureiq.catalog.flotta.openpa.base import OpenPABaseConnettore
from treasureiq.catalog.flotta.openpa.trasparenza import OpenPATrasparenzaConnettore
from treasureiq.catalog.flotta.openweb.base import OpenWebBaseConnettore
from treasureiq.catalog.flotta.openweb.trasparenza import OpenWebTrasparenzaConnettore
from treasureiq.catalog.flotta.peopleweb.base import PeopleWebBaseConnettore
from treasureiq.catalog.flotta.peopleweb.trasparenza import (
    PeopleWebTrasparenzaConnettore,
)


def flotta_connectors() -> tuple[SourceConnector, ...]:
    """The fleet's connector units, one per (platform × surface)."""
    return (
        MunicipiumBaseConnettore(),
        MunicipiumTrasparenzaConnettore(),
        ComWebBaseConnettore(),
        ComWebTrasparenzaConnettore(),
        PeopleWebBaseConnettore(),
        PeopleWebTrasparenzaConnettore(),
        OpenWebBaseConnettore(),
        OpenWebTrasparenzaConnettore(),
        OpenPABaseConnettore(),
        OpenPATrasparenzaConnettore(),
        EGovBaseConnettore(),
        EGovTrasparenzaConnettore(),
        HGateBaseConnettore(),
        HGateTrasparenzaConnettore(),
    )


def flotta_adapter() -> FlottaAdapter:
    """The single gate adapter shared by the whole fleet."""
    return FlottaAdapter()


__all__ = [
    "FLOTTA_ADAPTER_VERSION",
    "FLOTTA_MANIFEST",
    "FLOTTA_PLATFORMS",
    "FlottaAdapter",
    "ComWebBaseConnettore",
    "ComWebTrasparenzaConnettore",
    "EGovBaseConnettore",
    "EGovTrasparenzaConnettore",
    "HGateBaseConnettore",
    "HGateTrasparenzaConnettore",
    "MunicipiumBaseConnettore",
    "MunicipiumTrasparenzaConnettore",
    "OpenWebBaseConnettore",
    "OpenWebTrasparenzaConnettore",
    "OpenPABaseConnettore",
    "OpenPATrasparenzaConnettore",
    "PeopleWebBaseConnettore",
    "PeopleWebTrasparenzaConnettore",
    "flotta_connectors",
    "flotta_adapter",
]
