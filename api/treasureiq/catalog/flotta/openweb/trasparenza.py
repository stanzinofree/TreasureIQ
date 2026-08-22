"""OpenWeb connector: transparency index only (PDF reading is out of scope).

``leggi_openweb`` fills ``esito.amministrazione_trasparente``; this unit projects
that index into the catalog TRANSPARENCY surface. Versioned on its own (I2).
"""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaTrasparenzaConnettore

OPENWEB_TRASPARENZA_VERSION = "1.0.0"


class OpenWebTrasparenzaConnettore(FlottaTrasparenzaConnettore):
    platform_id = "openweb"
    name = "openweb.trasparenza"
    version = OPENWEB_TRASPARENZA_VERSION
