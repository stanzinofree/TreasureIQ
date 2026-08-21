"""Confirmation checks starting from persisted source entrypoints.

This module deliberately contains no discovery.  It reads the inventory,
fetches the saved AT/SP URLs, evaluates reachability and the known
fingerprint, then writes one check envelope per surface.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from treasureiq.catalog.checks import CheckResult, CheckStatus
from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import (
    FingerprintEvidence,
    RecognitionAction,
)
from treasureiq.catalog.service_contracts import SourceInventory
from treasureiq.ingest.host_guard import fetch_guardato
from treasureiq.ingest.piattaforma import Piattaforma, classifica_risposta, impronta_grezza


def _fingerprint(*, platform: str | None, headers: dict[str, str], html: str) -> str:
    raw = json.dumps(
        {"platform": platform, "raw": impronta_grezza(headers=headers, html=html)},
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_check(live_dir: Path, result: CheckResult, *, suffix: str = "") -> None:
    directory = live_dir / "check" / result.surface.value
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.source_id}{suffix}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(result.model_dump_json(indent=1), encoding="utf-8")
    temporary.replace(path)


def _confirm_one(
    *, source_id: str, surface: Surface, url: str, expected_platform: str | None,
    timeout: float,
) -> CheckResult:
    checked_at = datetime.now(timezone.utc)
    fetched = fetch_guardato(
        url, timeout=timeout, max_bytes=1_000_000,
        allow_one_cross_host_redirect=True,
    )
    if fetched is None:
        return CheckResult(
            source_id=source_id, surface=surface,
            status=CheckStatus.UNAVAILABLE, source_health=False,
            identity={"entrypoint_url": url},
            failure_reason="entrypoint_unreachable",
            action=RecognitionAction.REDISCOVER, checked_at=checked_at,
        )
    headers, data, final_url = fetched
    html = data.decode("utf-8", errors="replace")
    if surface is Surface.TRANSPARENCY:
        found = classifica_risposta(headers=dict(headers), html=html, includi_at=True).vincitore
        platform = found.piattaforma.value
        known = platform not in {Piattaforma.IGNOTA.value, Piattaforma.NON_TROVATA.value}
    else:
        # SP provider_hint is the persisted platform contract.  The check
        # must not infer a new vendor from generic HTML on an authenticated
        # portal; it only confirms that the known entrypoint is alive.
        platform = expected_platform
        known = bool(platform)
    healthy = known and 200 <= 200 < 400
    changed = bool(expected_platform and platform and expected_platform != platform)
    action = (
        RecognitionAction.REDISCOVER if changed
        else RecognitionAction.MANUAL_REVIEW if not known
        else RecognitionAction.KEEP
    )
    status = CheckStatus.OK if healthy and not changed else CheckStatus.MANUAL_REVIEW
    return CheckResult(
        source_id=source_id, surface=surface, status=status,
        source_health=True, completeness_score=1.0,
        recognition_score=1.0 if known and not changed else 0.0,
        coverage_score=1.0, connector_id="entrypoint_confirmation",
        connector_version="1.0.0", fingerprint_version="1.0",
        fingerprint=_fingerprint(platform=platform, headers=dict(headers), html=html),
        identity={"entrypoint_url": url, "final_url": final_url,
                  "platform": platform, "expected_platform": expected_platform},
        evidence=(FingerprintEvidence(
            key="platform", description="piattaforma invariata", matched=known and not changed,
            weight=1.0, observed=platform, expected=expected_platform,
        ),),
        failure_reason=(
            "platform_changed" if changed
            else "provider_not_recognized" if not known
            else None
        ),
        action=action, checked_at=checked_at,
    )


def confirm_inventory(*, live_dir: Path, source_id: str, timeout: float = 8.0) -> tuple[CheckResult, ...]:
    """Confirm persisted AT/SP entrypoints for one municipality, no discovery."""
    path = live_dir / "inventario" / f"{source_id}.json"
    inventory = SourceInventory.model_validate_json(path.read_text(encoding="utf-8"))
    results: list[CheckResult] = []
    if inventory.transparency_url:
        result = _confirm_one(
            source_id=source_id, surface=Surface.TRANSPARENCY,
            url=str(inventory.transparency_url),
            expected_platform=inventory.transparency_platform, timeout=timeout,
        )
        _write_check(live_dir, result)
        results.append(result)
    for index, portal in enumerate(inventory.service_portals):
        result = _confirm_one(
            source_id=source_id, surface=Surface.SERVICE_PORTAL,
            url=str(portal.url), expected_platform=portal.provider_hint,
            timeout=timeout,
        )
        _write_check(live_dir, result, suffix=f"-{index}")
        results.append(result)
    return tuple(results)
