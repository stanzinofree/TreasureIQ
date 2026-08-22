"""eGov/HGATE BASE connectors: office directory and contacts.

``leggi_egov`` fills ``esito.uffici`` via ``_leggi_uffici_egov`` (egov.py:420) —
so the office rail is ``uffici``-driven here exactly like the other fleet
platforms, and the projection is the shared one. ``aree_amministrative`` is a
separate display concern carried by the acquisition esito, not part of the BASE
office rail, so it needs no surface projection here.
"""

from __future__ import annotations

from treasureiq.catalog.flotta._base import FlottaBaseConnettore

EGOV_BASE_VERSION = "1.0.0"
HGATE_BASE_VERSION = "1.0.0"


class EGovBaseConnettore(FlottaBaseConnettore):
    platform_id = "egov"
    name = "egov.base"
    version = EGOV_BASE_VERSION


class HGateBaseConnettore(FlottaBaseConnettore):
    platform_id = "hgate"
    name = "hgate.base"
    version = HGATE_BASE_VERSION
