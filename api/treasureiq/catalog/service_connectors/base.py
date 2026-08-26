"""Shared seam for service connectors of a platform family (Ramo 3, Slice 4).

A service connector resolves a ``ServiceKey`` into a ``ServiceReference`` by
querying one municipal platform.  The network is behind an injectable
``ServiceFetcher`` so the connectors and their golden tests stay net-free: the
real implementation talks httpx, the test stub returns fixtures.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import AnyHttpUrl, Field

from treasureiq.catalog.contracts import _StrictModel


class ServiceCandidate(_StrictModel):
    """One service found by discovery — a candidate, not yet a canonical service.
    ``native_id`` is the stable, platform-native identity (the title changes, the
    id does not): WordPress passes ``str(id)``, ComWeb the scheda's identifying
    path segment. Different URLs are never merged on title similarity."""

    native_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: AnyHttpUrl
    #: Platform-native content class, when the source exposes one (OpenPA/eZ Find:
    #: ``classIdentifier`` — ``public_service``/``document``/``article``/...).
    #: ``None`` for families without the notion (WP/ComWeb): the class-aware gate
    #: is opt-in per connector, so ``None`` means "no class filter applies here".
    native_class: str | None = None


class ServiceFetcher(Protocol):
    """The only network seam of a service connector.

    The signature is platform-neutral: no WordPress concept (``rest_base``)
    leaks here.  ``base_url`` is the family's discovery entry point, computed by
    the connector from its ``mappa`` (WP: the REST collection URL; ComWeb: the
    services index root).  Each implementation owns how it turns that entry point
    into candidates — REST ``?search=`` for WordPress, index+category scrape for
    ComWeb — plus timeouts, HTTP status, malformed responses, the host guard, and
    the no-login/no-cookie discipline.  Everything else in the connector is pure
    and deterministic.
    """

    def scopri_servizi(
        self,
        *,
        base_url: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        """Discover candidate services from the family entry point.  Never raises
        for a reachable-but-empty or malformed source: returns ``()``."""

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        """Fetch one service page's HTML, or ``None`` if unreadable.  Must
        enforce the official-host guard before fetching."""
