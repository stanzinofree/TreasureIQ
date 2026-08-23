"""ComWeb AT connector: the transparency index, versioned on its own."""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaTrasparenzaConnettore

COMWEB_TRASPARENZA_VERSION = "1.0.0"


class ComWebTrasparenzaConnettore(FlottaTrasparenzaConnettore):
    platform_id = "comweb"
    name = "comweb.trasparenza"
    version = COMWEB_TRASPARENZA_VERSION
