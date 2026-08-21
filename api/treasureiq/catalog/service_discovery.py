"""Deterministic discovery of service-portal candidates from BASE."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from treasureiq.catalog.service_contracts import (
    AuthenticationMethod,
    ServicePortalCandidate,
    ServicePortalRole,
    SourceInventory,
)
from treasureiq.catalog.discovery_profiles import profile_for_base
from treasureiq.catalog.service_portals import group_service_portal_candidates

logger = logging.getLogger(__name__)

_SERVICE_MARKERS = (
    "area privata", "area personale", "servizi online", "avvio istanze",
    "istanze online", "sportello telematico", "accedi ai servizi",
    "portale dei servizi", "servizi demografici", "prenota appuntamento",
    "agenda smart",
)
_AUTH_MARKERS = ("spid", "cie", "cns", "login", "accedi", "privat")
_NON_PORTAL_MARKERS = (
    "newsletter", "rss", "feed", "albo pretorio", "wp-admin", "wp-login",
    "wp admin", "wp login",
)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def _provider_hint(url: str) -> str | None:
    value = url.lower()
    for marker, provider in (
        ("urbi", "urbi"),
        ("municipium", "municipium"),
        ("sportellotelematico", "sportello_telematico"),
        ("agenda-smart", "agenda_smart"),
        ("comune-online", "comune_online"),
        ("cportal", "cportal"),
        ("filodiretto", "filodiretto"),
    ):
        if marker in value:
            return provider
    return None


def _role(label: str, url: str) -> ServicePortalRole:
    value = f"{label} {url}".lower().replace("-", " ").replace("_", " ")
    if any(marker in value for marker in (
        "prenota appuntamento", "prenotazioni", "prenotaappuntamenti",
        "agenda smart", "agenda-smart",
    )):
        return ServicePortalRole.APPOINTMENT
    if any(marker in value for marker in (
        "area personale", "area privata", "areariservata", "autenticazione",
        "accesso ai servizi", "login", "filodiretto",
    )):
        return ServicePortalRole.PERSONAL_AREA
    if any(marker in value for marker in (
        "sportello telematico", "sportellotelematico", "sportello",
    )):
        return ServicePortalRole.TELEMATICS_DESK
    if any(marker in value for marker in (
        "servizi online", "servizi demografici", "bacheca servizi",
        "servizi esterni", "servizio online", "avvio istanze",
        "istanze online",
    )):
        return ServicePortalRole.ONLINE_SERVICE
    return ServicePortalRole.UNKNOWN


def discover_service_portal_candidates(
    *, base_url: str, html_home: str, base_platform: str | None = None,
    discovered_at: datetime | None = None
) -> tuple[ServicePortalCandidate, ...]:
    """Extract candidate portals using BASE hints plus generic fallback."""
    when = discovered_at or datetime.now(timezone.utc)
    parser = _Links()
    parser.feed(html_home)
    result: list[ServicePortalCandidate] = []
    seen: set[str] = set()
    for href, label in parser.links:
        absolute = urljoin(base_url, href.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        haystack = f"{label} {absolute}".lower().replace("-", " ").replace("_", " ")
        profile = profile_for_base(base_platform)
        markers = _SERVICE_MARKERS + profile.service_markers
        if not any(marker in haystack for marker in markers):
            continue
        if any(marker in haystack for marker in _NON_PORTAL_MARKERS):
            continue
        key = absolute.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        authentication = tuple(
            method for marker, method in (
                ("spid", AuthenticationMethod.SPID),
                ("cie", AuthenticationMethod.CIE),
                ("cns", AuthenticationMethod.CNS),
                ("password", AuthenticationMethod.PASSWORD),
            ) if marker in haystack
        )
        if not authentication and any(marker in haystack for marker in _AUTH_MARKERS):
            authentication = (AuthenticationMethod.UNKNOWN,)
        result.append(ServicePortalCandidate(
            url=absolute,
            label=label or absolute,
            source_url=base_url,
            role=_role(label, absolute),
            provider_hint=_provider_hint(absolute),
            authentication=authentication,
            discovered_at=when,
        ))
    return tuple(result)


def update_source_inventory(
    *, live_dir: Path, source_id: str, base_url: str,
    base_platform: str | None, base_fingerprint: str | None,
    transparency_url: str | None, transparency_platform: str | None,
    candidates: tuple[ServicePortalCandidate, ...],
    confirmed_at: datetime | None = None,
    base_source_health: bool | None = None,
    base_failure_reason: str | None = None,
) -> SourceInventory:
    """Merge BASE/AT facts into an atomic municipality inventory."""
    when = confirmed_at or datetime.now(timezone.utc)
    path = live_dir / "inventario" / f"{source_id}.json"
    previous: SourceInventory | None = None
    if path.exists():
        try:
            previous = SourceInventory.model_validate_json(path.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning("inventario illeggibile per %s", source_id)
    effective_candidates = candidates or (previous.service_portals if previous else ())
    inventory = SourceInventory(
        source_id=source_id, base_url=base_url, base_platform=base_platform,
        base_fingerprint=base_fingerprint, base_confirmed_at=when,
        base_source_health=base_source_health,
        base_failure_reason=base_failure_reason,
        transparency_url=transparency_url or (previous.transparency_url if previous else None),
        transparency_platform=transparency_platform or (previous.transparency_platform if previous else None),
        transparency_fingerprint=previous.transparency_fingerprint if previous else None,
        transparency_confirmed_at=previous.transparency_confirmed_at if previous else None,
        service_portals=effective_candidates,
        service_portal_groups=group_service_portal_candidates(effective_candidates),
        updated_at=when,
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(inventory.model_dump_json(indent=1), "utf-8")
        temporary.replace(path)
    except OSError as exc:
        logger.warning("inventario non scrivibile (%s): %s", path, exc)
    return inventory
