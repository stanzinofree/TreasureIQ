"""Refresh-support predicate: single source of truth for the sweep queue.

The oldest-first refresh queue starves write-capable comuni when a platform
without a dedicated reader stays at its head (its no-op never bumps
``letto_il``). ``refresh_supportato`` lets the sweep selection skip those, so it
must agree exactly with the dispatch chain of ``refresh_dati_connettore``.
"""

from __future__ import annotations

import pytest

from treasureiq.connettore import PIATTAFORME_REFRESH, refresh_supportato

# Platforms that DO have a dedicated reader in refresh_dati_connettore.
SUPPORTATE = [
    "municipium",
    "egov",
    "hgate",
    "peopleweb",
    "openweb",
    "wp_design_comuni",
    "wordpress_generico",
    "comunibootstrapitalia",
    "comweb",
    "openpa",
]

# Platforms with NO reader: refresh is a no-op that never updates freshness.
# "wordpress_agid" is a legacy stored value no longer in the enum — exactly the
# string that clogged the pilot queue.
NON_SUPPORTATE = [
    "wordpress_agid",
    "dotnetnuke",
    "flexcmp",
    "isweb",
    "citypal",
    "agenda_smart",
    "magnolia",
    "drupal",
    "joomla",
    "ignota",
    None,
    "",
]


@pytest.mark.parametrize("piattaforma", SUPPORTATE)
def test_supportate_true(piattaforma: str) -> None:
    assert refresh_supportato(piattaforma) is True


@pytest.mark.parametrize("piattaforma", NON_SUPPORTATE)
def test_non_supportate_false(piattaforma) -> None:
    assert refresh_supportato(piattaforma) is False


def test_frozenset_e_lista_supportate_coincidono() -> None:
    # Guards drift between the documented set and the readers it mirrors.
    assert PIATTAFORME_REFRESH == frozenset(SUPPORTATE)
