"""Municipium AT connector: the transparency index, versioned on its own."""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaTrasparenzaConnettore

MUNICIPIUM_TRASPARENZA_VERSION = "1.0.0"


class MunicipiumTrasparenzaConnettore(FlottaTrasparenzaConnettore):
    platform_id = "municipium"
    name = "municipium.trasparenza"
    version = MUNICIPIUM_TRASPARENZA_VERSION
