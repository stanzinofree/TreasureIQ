"""OpenWeb BASE connector: office directory and contacts.

The v0 ``leggi_openweb`` already fills ``esito.uffici`` (openweb.py); this unit
projects that acquired esito into the catalog BASE surface, exactly like the
municipium/comweb/peopleweb units. Versioned on its own (I2).
"""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaBaseConnettore

OPENWEB_BASE_VERSION = "1.0.0"


class OpenWebBaseConnettore(FlottaBaseConnettore):
    platform_id = "openweb"
    name = "openweb.base"
    version = OPENWEB_BASE_VERSION
