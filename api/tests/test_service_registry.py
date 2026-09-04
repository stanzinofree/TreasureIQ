"""Golden tests for the service registry factory + fetch coordinator (Slice 5).

Pure, no network: the factory only *constructs* connectors (an executor is
injected, never called here). Pin §1.1/§1.2 — the factory populates the
previously-empty registry with the WP/AgID pilot, ``resolve`` selects on
``supports`` (right platform vs wrong), and the process fetch coordinator is a
single shared, thread-safe (``EsecutoreFetchSerializzato``) instance.
"""

from __future__ import annotations

from treasureiq.catalog import service_registry
from treasureiq.catalog.fetch_runtime import EsecutoreFetchSerializzato
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_connectors.openweb_service import (
    OpenWebServiceConnector,
)
from treasureiq.catalog.service_connectors.wordpress_agid import (
    WordPressAgidServiceConnector,
)
from treasureiq.catalog.service_contracts import ServiceKey


class _EsecutoreFinto:
    """Placeholder executor: the factory must not touch it at build time."""

    def esegui(self, *a, **k):  # pragma: no cover - must never be called here
        raise AssertionError("il factory non deve eseguire fetch")


def _request():
    return service_request(source_id="058003", service_key=ServiceKey.CARTA_IDENTITA)


# 1 — the factory populates the registry with the WP/AgID pilot
def test_factory_contiene_wp_agid():
    reg = service_registry.default_service_registry(_EsecutoreFinto())
    connettore = reg.resolve(request=_request(), platform_id="wordpress_agid")
    assert isinstance(connettore, WordPressAgidServiceConnector)


# 2 — resolve selects on supports: a foreign platform gets no connector
def test_resolve_piattaforma_estranea_none():
    reg = service_registry.default_service_registry(_EsecutoreFinto())
    assert reg.resolve(request=_request(), platform_id="municipium") is None
    assert reg.resolve(request=_request(), platform_id="") is None


# 2b — the factory selects OpenWeb on peopleweb, independently of order
def test_factory_seleziona_openweb_su_peopleweb():
    reg = service_registry.default_service_registry(_EsecutoreFinto())
    connettore = reg.resolve(request=_request(), platform_id="peopleweb")
    # peopleweb resolves to OpenWeb and NOT to the WP/AgID pilot, even though
    # both share the same /wp-json/wp/v2/servizi surface: selection is by
    # platform gate, not registration order. OpenWeb is a WP/AgID subclass, so
    # assert the EXACT type — the plain pilot must not answer for peopleweb.
    assert type(connettore) is OpenWebServiceConnector


# 2c — WP/AgID and OpenWeb do not cross-select each other's platform
def test_wp_e_openweb_non_si_scambiano_piattaforma():
    reg = service_registry.default_service_registry(_EsecutoreFinto())
    # wordpress_agid → the pilot, never OpenWeb.
    wp = reg.resolve(request=_request(), platform_id="wordpress_agid")
    assert isinstance(wp, WordPressAgidServiceConnector)
    assert not isinstance(wp, OpenWebServiceConnector)
    # peopleweb → OpenWeb only; the pilot's gate rejects it.
    ow = reg.resolve(request=_request(), platform_id="peopleweb")
    assert isinstance(ow, OpenWebServiceConnector)


# 3 — the coordinator is a single shared thread-safe instance
def test_coordinatore_singleton_thread_safe():
    a = service_registry.service_query_fetch_coordinator()
    b = service_registry.service_query_fetch_coordinator()
    assert a is b
    assert isinstance(a, EsecutoreFetchSerializzato)


# 4 — env parsing helpers fall back on absent/invalid/out-of-range values
def test_intero_env_fallback(monkeypatch):
    monkeypatch.delenv(service_registry._ENV_BUDGET, raising=False)
    assert service_registry._intero_env(service_registry._ENV_BUDGET, 30) == 30
    monkeypatch.setenv(service_registry._ENV_BUDGET, "non-un-numero")
    assert service_registry._intero_env(service_registry._ENV_BUDGET, 30) == 30
    monkeypatch.setenv(service_registry._ENV_BUDGET, "0")
    assert service_registry._intero_env(service_registry._ENV_BUDGET, 30) == 30
    monkeypatch.setenv(service_registry._ENV_BUDGET, "7")
    assert service_registry._intero_env(service_registry._ENV_BUDGET, 30) == 7


def test_float_env_fallback(monkeypatch):
    monkeypatch.delenv(service_registry._ENV_WINDOW_S, raising=False)
    assert service_registry._float_env(service_registry._ENV_WINDOW_S, 3600.0) == 3600.0
    monkeypatch.setenv(service_registry._ENV_WINDOW_S, "nan-ish")
    assert service_registry._float_env(service_registry._ENV_WINDOW_S, 3600.0) == 3600.0
    monkeypatch.setenv(service_registry._ENV_WINDOW_S, "0")
    assert service_registry._float_env(service_registry._ENV_WINDOW_S, 3600.0) == 3600.0
    monkeypatch.setenv(service_registry._ENV_WINDOW_S, "120.5")
    assert service_registry._float_env(service_registry._ENV_WINDOW_S, 3600.0) == 120.5
