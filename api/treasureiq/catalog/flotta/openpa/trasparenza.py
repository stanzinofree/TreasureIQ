"""OpenPA connector: transparency index only (PDF reading is out of scope).

``leggi_openpa`` fills ``esito.amministrazione_trasparente``; this unit projects
that index into the catalog TRANSPARENCY surface. Versioned on its own (I2).
"""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaTrasparenzaConnettore

OPENPA_TRASPARENZA_VERSION = "1.0.0"


class OpenPATrasparenzaConnettore(FlottaTrasparenzaConnettore):
    platform_id = "openpa"
    name = "openpa.trasparenza"
    version = OPENPA_TRASPARENZA_VERSION
