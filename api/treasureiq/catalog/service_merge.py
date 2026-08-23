"""Read-time merge of verified SP provenance onto a BASE ``ServiceReference``.

Ramo 3, Slice 6.  The BASE connector (WP/AgID) owns the service identity and its
access options; the SP discovery persists portal entrypoints in
``SourceInventory.service_portals``.  This module enriches an
``AUTHENTICATED_ONLINE`` option with the SP provenance (platform, role,
authentication, fingerprint) **only** when a verifiable per-link association
exists (§2): the option's URL matches a discovered SP entrypoint of the *same*
source.  It is a pure function — no I/O, no cache write, no network — and it
never creates, renames, promotes or reorders options (§1, guards G1–G7).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from treasureiq.catalog.service_contracts import (
    AuthenticationMethod,
    ServiceAccessMode,
    ServiceAccessOption,
    ServicePortalRole,
    ServiceReference,
    SourceInventory,
)


class _Evidence:
    """The SP fields an entrypoint match can contribute to enrichment.

    A ``ServicePortalCandidate`` carries all of them; a
    ``ServicePortalGroup`` entrypoint carries only ``platform_id`` and a role
    (when the group declares exactly one), never an invented one.
    """

    __slots__ = ("platform_id", "role", "fingerprint", "provider_hint", "authentication")

    def __init__(
        self,
        *,
        platform_id: str | None,
        role: ServicePortalRole | None,
        fingerprint: str | None,
        provider_hint: str | None,
        authentication: tuple[AuthenticationMethod, ...],
    ) -> None:
        self.platform_id = platform_id
        self.role = role
        self.fingerprint = fingerprint
        self.provider_hint = provider_hint
        self.authentication = authentication


def _host_path(url: str) -> tuple[str, str]:
    """Host+path normalised for comparison: scheme- and ``www.``-insensitive,
    trailing-slash-insensitive.  This is the base comparison key (§2)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return host, path


def _query(url: str) -> str:
    return urlsplit(url).query


def _matchables(inventory: SourceInventory) -> list[tuple[str, _Evidence]]:
    """Every SP entrypoint that could carry per-link evidence, as
    ``(url, evidence)``.  A candidate is richer than a group entrypoint, so when
    the same normalised URL appears on both, the candidate wins — this also
    prevents a group's logical duplicate of a candidate from inflating the
    ambiguity count (§2)."""
    by_key: dict[tuple[str, str, str], tuple[str, _Evidence, bool]] = {}

    def _put(url: str, evidence: _Evidence, *, is_candidate: bool) -> None:
        host, path = _host_path(url)
        key = (host, path, _query(url))
        existing = by_key.get(key)
        # Candidate evidence supersedes a group entrypoint at the same URL.
        if existing is None or (is_candidate and not existing[2]):
            by_key[key] = (url, evidence, is_candidate)

    for candidate in inventory.service_portals:
        _put(
            str(candidate.url),
            _Evidence(
                platform_id=candidate.platform_id,
                role=candidate.role,
                fingerprint=candidate.fingerprint,
                provider_hint=candidate.provider_hint,
                authentication=candidate.authentication,
            ),
            is_candidate=True,
        )
    for group in inventory.service_portal_groups:
        role = group.roles[0] if len(group.roles) == 1 else None
        for entrypoint in group.entrypoints:
            _put(
                str(entrypoint),
                _Evidence(
                    platform_id=group.platform_id,
                    role=role,
                    fingerprint=None,
                    provider_hint=None,
                    authentication=(),
                ),
                is_candidate=False,
            )
    return [(url, evidence) for url, evidence, _ in by_key.values()]


def _match(base_url: str, matchables: list[tuple[str, _Evidence]]) -> _Evidence | None:
    """The SP evidence associated to ``base_url`` by per-link evidence, or
    ``None``.  Ambiguity is always a non-match, never a first-wins choice (§2)."""
    base_hp = _host_path(base_url)
    base_query = _query(base_url)

    if base_query:
        # Base carries a query → exact match on host+path+query only.
        exact = [
            ev
            for url, ev in matchables
            if _host_path(url) == base_hp and _query(url) == base_query
        ]
        return exact[0] if len(exact) == 1 else None

    # Base has no query → host+path; more than one candidate is ambiguous.
    same = [ev for url, ev in matchables if _host_path(url) == base_hp]
    return same[0] if len(same) == 1 else None


def _ordered_union(
    left: tuple[AuthenticationMethod, ...], right: tuple[AuthenticationMethod, ...]
) -> tuple[AuthenticationMethod, ...]:
    """Left's methods first (order preserved), then right's not already present.
    No method is invented: only those declared on one side or the other (G4)."""
    merged: list[AuthenticationMethod] = list(left)
    for method in right:
        if method not in merged:
            merged.append(method)
    return tuple(merged)


def _enrich(option: ServiceAccessOption, evidence: _Evidence) -> ServiceAccessOption:
    """A new option with missing fields filled from ``evidence``.  ``mode``,
    ``url``, ``requires_authentication`` and ``official`` are BASE-owned and
    never touched (G3): an ``AUTHENTICATED_ONLINE`` is never promoted."""
    return option.model_copy(
        update={
            "provider": option.provider if option.provider is not None else evidence.provider_hint,
            "authentication": _ordered_union(option.authentication, evidence.authentication),
            # Solo campi mancanti: una provenienza già presente non viene mai
            # cancellata da un candidato con metadati incompleti (conservazione
            # della provenienza + idempotenza, §3).
            "sp_platform_id": (
                option.sp_platform_id
                if option.sp_platform_id is not None
                else evidence.platform_id
            ),
            "sp_role": option.sp_role if option.sp_role is not None else evidence.role,
            "sp_fingerprint": (
                option.sp_fingerprint
                if option.sp_fingerprint is not None
                else evidence.fingerprint
            ),
        }
    )


def merge_service_portals(
    *,
    source_id: str,
    reference: ServiceReference,
    inventory: SourceInventory | None,
) -> ServiceReference:
    """Enrich the reference's ``AUTHENTICATED_ONLINE`` options with verified SP
    provenance, read-time and pure (§3).

    ``source_id`` is explicit in the signature (G7): it is never inferred from
    ``service_id``.  Returns ``reference`` unchanged (identity) when there is no
    inventory, the ``source_id`` differs, the inventory has no SP entrypoints, or
    no option has a per-link match.  Idempotent and deterministic: option order
    is preserved and re-running on an enriched reference changes nothing.
    """
    if inventory is None or inventory.source_id != source_id:
        return reference  # G6/G7 — identity, never a cross-source merge.
    if not inventory.service_portals and not inventory.service_portal_groups:
        return reference  # G6 — empty inventory is identity.

    matchables = _matchables(inventory)
    new_options: list[ServiceAccessOption] = []
    changed = False
    for option in reference.options:
        # G1 — only AUTHENTICATED_ONLINE is inspected; DOWNLOAD/INFORMATION intact.
        if option.mode is not ServiceAccessMode.AUTHENTICATED_ONLINE:
            new_options.append(option)
            continue
        evidence = _match(str(option.url), matchables)  # G2 — per-link evidence only.
        if evidence is None:
            new_options.append(option)
            continue
        enriched = _enrich(option, evidence)
        new_options.append(enriched)
        if enriched != option:
            changed = True

    if not changed:
        return reference  # No association fired → byte-identical identity.
    return reference.model_copy(update={"options": tuple(new_options)})
