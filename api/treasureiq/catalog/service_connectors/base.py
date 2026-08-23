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
    """One service found by a REST search — a candidate, not yet a canonical
    service.  ``wordpress_id`` is the stable identity (the title changes, the id
    does not); different URLs are never merged on title similarity."""

    wordpress_id: int = Field(gt=0)
    title: str = Field(min_length=1)
    url: AnyHttpUrl


class ServiceFetcher(Protocol):
    """The only network seam of a service connector.

    Implementations own: REST URL building, term encoding, ``per_page`` limit,
    timeouts, HTTP status, malformed JSON, the host guard on the fetched page,
    and the no-login/no-cookie discipline.  Everything else in the connector is
    pure and deterministic.
    """

    def cerca_servizi(
        self,
        *,
        base_url: str,
        rest_base: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        """Run one ``?search=`` query against the service CPT.  Never raises for
        a reachable-but-empty or malformed source: returns ``()``."""

    def leggi_pagina(self, *, url: str, official_host: str) -> str | None:
        """Fetch one service page's HTML, or ``None`` if unreadable.  Must
        enforce the official-host guard before fetching."""
