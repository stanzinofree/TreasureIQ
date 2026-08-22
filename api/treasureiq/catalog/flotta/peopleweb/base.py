"""PeopleWeb BASE connector: office directory and contacts, versioned on its own."""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaBaseConnettore

PEOPLEWEB_BASE_VERSION = "1.0.0"


class PeopleWebBaseConnettore(FlottaBaseConnettore):
    platform_id = "peopleweb"
    name = "peopleweb.base"
    version = PEOPLEWEB_BASE_VERSION
