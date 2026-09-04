"""Service connector for the PeopleWeb–OpenWeb platform (Base candidate).

OpenWeb is WordPress/AgID on the service surface: the same ``servizi`` CPT at
``{site}/wp-json/wp/v2/servizi``, the same ``id/title/link`` dialect, the same
``?search={term}`` discovery. Recon (5 comuni, shared recogniser) confirmed the
gate profile matches the WP/AgID pilot verbatim. So this connector adds **no new
family logic**: it reuses ``WordPressAgidServiceConnector`` whole — discovery
target, confirm, options, esito — and only shifts the platform gate.

Why a distinct connector and not just a wider allowlist on the WP/AgID pilot:

- ``peopleweb`` is **two vendors under one platform_id** — OpenWeb (WordPress,
  ``servizi.esposto=True``) and Siscom (not WordPress, ``servizi.esposto=False``).
  The gate must admit ``peopleweb`` without touching the WP/AgID manifest, so the
  existing WP/AgID installations keep their exact behaviour.
- Siscom is excluded **structurally, not by name**: the inherited
  ``_discovery_target`` returns ``None`` when ``not mappa.servizi.esposto``, and
  Siscom comuni carry ``esposto=False``. No Siscom-specific string is needed.
- ``provider``/``name`` stay distinct (``openweb_service``) so promotions and
  provenance never conflate the two families.
"""

from __future__ import annotations

from treasureiq.catalog.data_contracts import ConnectorRef
from treasureiq.catalog.service_connectors.wordpress_agid import (
    WordPressAgidServiceConnector,
)

#: The single platform_id OpenWeb comuni carry at runtime. PeopleWeb–Siscom
#: shares this id but is filtered out downstream by ``servizi.esposto=False``
#: in the inherited ``_discovery_target`` — the discriminant is the exposed
#: service CPT, not the platform string.
_PIATTAFORME_OPENWEB = frozenset({"peopleweb"})

_CONNECTOR = ConnectorRef(name="openweb_service", version="1")


class OpenWebServiceConnector(WordPressAgidServiceConnector):
    """Resolve a ``ServiceKey`` on PeopleWeb–OpenWeb portals (WordPress/AgID).

    Inherits the entire WP/AgID resolution — ``_discovery_target`` (composes
    ``{site}/wp-json/wp/v2/servizi`` and self-excludes non-exposed Siscom),
    confirm-exactly-one, options, esito. Only the platform gate, the provider
    tag and the ``service_id`` prefix are re-pinned so OpenWeb is selected
    independently of registration order and stays distinct in the catalog."""

    name = "openweb_service"
    version = "1"
    _CONNECTOR = _CONNECTOR
    _PIATTAFORME = _PIATTAFORME_OPENWEB
    _PREFISSO = "openweb"
    _PROVIDER_PLATFORM = "openweb"
