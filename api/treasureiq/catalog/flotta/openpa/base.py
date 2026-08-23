"""OpenPA BASE connector: office directory and contacts.

The v0 ``leggi_openpa`` already fills ``esito.uffici`` (openpa.py); this unit
projects that acquired esito into the catalog BASE surface, exactly like the
municipium/comweb/peopleweb units. Versioned on its own (I2).
"""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaBaseConnettore

OPENPA_BASE_VERSION = "1.0.0"


class OpenPABaseConnettore(FlottaBaseConnettore):
    platform_id = "openpa"
    name = "openpa.base"
    version = OPENPA_BASE_VERSION
