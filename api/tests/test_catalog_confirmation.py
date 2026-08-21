"""The AT confirmation envelope produced *after* the registry rewiring (T2 A).

``_confirm_one`` for ``Surface.TRANSPARENCY`` now recognises the platform through
``firma_da_registro`` (the registry) instead of the legacy ``classifica_risposta``.
The adapter unit tests cover the seam in isolation; the review flagged that no test
exercises the *whole* check envelope the confirmation writes once the adapter is in
the path. These do: real registry (no recognition mock), only the network fetch
stubbed, asserting status/action/scores/evidence/failure_reason end to end.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from treasureiq.catalog import confirmation as confirmation_mod
from treasureiq.catalog.checks import CheckStatus
from treasureiq.catalog.confirmation import _confirm_one, confirm_inventory
from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition import RecognitionAction
from treasureiq.catalog.service_contracts import SourceInventory
from treasureiq.ingest.piattaforma import Piattaforma

# urbi AT signature — the same fixture the adapter unit test recognises as URBI.
_URBI_AT = '<a href="/portale/ur1UR033.sto?ente=x">Amministrazione Trasparente</a>'
_AT_URL = "https://trasparenza.comune.example.it/portale/"


def _stub_fetch(monkeypatch, *, html: str | None, headers: dict[str, str] | None = None):
    """Replace only the network hop; the recognition stays real."""
    def fake(url, **_kw):
        if html is None:
            return None
        return httpx.Headers(headers or {}), html.encode("utf-8"), url
    monkeypatch.setattr(confirmation_mod, "fetch_guardato", fake)


def test_at_envelope_recognised_and_expected_matches(monkeypatch):
    _stub_fetch(monkeypatch, html=_URBI_AT)
    result = _confirm_one(
        source_id="058003", surface=Surface.TRANSPARENCY, url=_AT_URL,
        expected_platform=Piattaforma.URBI.value, timeout=1.0,
    )
    assert result.surface is Surface.TRANSPARENCY
    assert result.status is CheckStatus.OK
    assert result.action is RecognitionAction.KEEP
    assert result.source_health is True
    assert result.recognition_score == 1.0
    assert result.completeness_score == 1.0
    assert result.failure_reason is None
    assert result.connector_id == "entrypoint_confirmation"
    assert result.identity["platform"] == Piattaforma.URBI.value
    assert result.identity["expected_platform"] == Piattaforma.URBI.value
    assert len(result.evidence) == 1
    assert result.evidence[0].matched is True


def test_at_envelope_recognised_but_platform_changed(monkeypatch):
    # AT is really urbi, but the inventory expected a different vendor: the
    # confirmation must flag drift, not silently overwrite the expectation.
    _stub_fetch(monkeypatch, html=_URBI_AT)
    result = _confirm_one(
        source_id="058003", surface=Surface.TRANSPARENCY, url=_AT_URL,
        expected_platform=Piattaforma.COMWEB.value, timeout=1.0,
    )
    assert result.status is CheckStatus.MANUAL_REVIEW
    assert result.action is RecognitionAction.REDISCOVER
    assert result.failure_reason == "platform_changed"
    assert result.recognition_score == 0.0
    assert result.identity["platform"] == Piattaforma.URBI.value
    assert result.identity["expected_platform"] == Piattaforma.COMWEB.value
    assert result.evidence[0].matched is False


def test_at_envelope_unrecognised_is_manual_review(monkeypatch):
    # Registry miss → adapter returns the IGNOTA sentinel → not known.
    _stub_fetch(monkeypatch, html="<html><body>nulla di riconoscibile</body></html>")
    result = _confirm_one(
        source_id="058003", surface=Surface.TRANSPARENCY, url=_AT_URL,
        expected_platform=None, timeout=1.0,
    )
    assert result.status is CheckStatus.MANUAL_REVIEW
    assert result.action is RecognitionAction.MANUAL_REVIEW
    assert result.failure_reason == "provider_not_recognized"
    assert result.recognition_score == 0.0
    assert result.identity["platform"] == Piattaforma.IGNOTA.value
    assert result.evidence[0].matched is False


def test_at_envelope_unreachable_entrypoint(monkeypatch):
    # The adapter is never reached when the fetch fails; the envelope must still
    # be the uniform UNAVAILABLE shape, not an exception.
    _stub_fetch(monkeypatch, html=None)
    result = _confirm_one(
        source_id="058003", surface=Surface.TRANSPARENCY, url=_AT_URL,
        expected_platform=Piattaforma.URBI.value, timeout=1.0,
    )
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.action is RecognitionAction.REDISCOVER
    assert result.failure_reason == "entrypoint_unreachable"
    assert result.source_health is False


def test_confirm_inventory_writes_at_check_from_registry(monkeypatch, tmp_path):
    """End to end: inventory on disk → confirm_inventory → check json written,
    with the AT platform recognised through the registry."""
    _stub_fetch(monkeypatch, html=_URBI_AT)
    inventory = SourceInventory(
        source_id="058003",
        base_url="https://comune.example.it/",
        transparency_url=_AT_URL,
        transparency_platform=Piattaforma.URBI.value,
        updated_at=datetime.now(timezone.utc),
    )
    inventory_dir = tmp_path / "inventario"
    inventory_dir.mkdir(parents=True)
    (inventory_dir / "058003.json").write_text(
        inventory.model_dump_json(), encoding="utf-8"
    )

    results = confirm_inventory(live_dir=tmp_path, source_id="058003", timeout=1.0)

    assert len(results) == 1
    assert results[0].surface is Surface.TRANSPARENCY
    assert results[0].status is CheckStatus.OK
    assert results[0].identity["platform"] == Piattaforma.URBI.value
    # The check envelope is persisted per surface, not only returned.
    written = tmp_path / "check" / "transparency" / "058003.json"
    assert written.exists()
    assert Piattaforma.URBI.value in written.read_text(encoding="utf-8")
