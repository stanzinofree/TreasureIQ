"""PeopleWeb AT connector: the transparency index, versioned on its own."""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaTrasparenzaConnettore

PEOPLEWEB_TRASPARENZA_VERSION = "1.0.0"


class PeopleWebTrasparenzaConnettore(FlottaTrasparenzaConnettore):
    platform_id = "peopleweb"
    name = "peopleweb.trasparenza"
    version = PEOPLEWEB_TRASPARENZA_VERSION
