"""Normalization of SP endpoints into logical portal groups."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from treasureiq.catalog.service_contracts import (
    ServicePortalCandidate,
    ServicePortalGroup,
)


def group_service_portal_candidates(
    candidates: tuple[ServicePortalCandidate, ...] | list[ServicePortalCandidate],
) -> tuple[ServicePortalGroup, ...]:
    """Group endpoints by recognized platform, otherwise by host.

    A missing platform never becomes a fake vendor: the fallback key is only
    a stable portal bucket and remains marked ``unknown``.
    """
    buckets: dict[str, list[ServicePortalCandidate]] = {}
    for candidate in candidates:
        platform = candidate.platform_id or candidate.provider_hint
        host = (urlsplit(str(candidate.url)).hostname or "unknown").lower()
        key = platform or f"host:{host}"
        buckets.setdefault(key, []).append(candidate)
    groups: list[ServicePortalGroup] = []
    for key, items in sorted(buckets.items()):
        platform = items[0].platform_id or items[0].provider_hint
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        groups.append(ServicePortalGroup(
            portal_id=f"sp:{digest}",
            platform_id=platform,
            entrypoints=tuple(item.url for item in items),
            roles=tuple(dict.fromkeys(item.role for item in items)),
            capabilities=tuple(dict.fromkeys(
                capability for item in items for capability in item.capabilities
            )),
            recognition_status=(
                "confirmed" if platform and all(item.recognition_status == "confirmed" for item in items)
                else "unknown"
            ),
        ))
    return tuple(groups)
