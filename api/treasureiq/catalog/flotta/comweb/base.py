"""ComWeb BASE connector: office directory and contacts, versioned on its own."""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaBaseConnettore

COMWEB_BASE_VERSION = "1.0.0"


class ComWebBaseConnettore(FlottaBaseConnettore):
    platform_id = "comweb"
    name = "comweb.base"
    version = COMWEB_BASE_VERSION
