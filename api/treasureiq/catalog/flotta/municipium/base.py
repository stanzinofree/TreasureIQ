"""Municipium BASE connector: office directory and contacts.

Versioned on its own — a fingerprint recorded against ``municipium.base`` carries
this version, and bumping it never touches ComWeb or PeopleWeb.
"""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaBaseConnettore

MUNICIPIUM_BASE_VERSION = "1.0.0"


class MunicipiumBaseConnettore(FlottaBaseConnettore):
    platform_id = "municipium"
    name = "municipium.base"
    version = MUNICIPIUM_BASE_VERSION
