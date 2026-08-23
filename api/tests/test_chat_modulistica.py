"""Ramo 3 — Modulistica, primo incremento SP (contratto §5).

Pin the chat wiring of the service-portal pointer:

* deterministic candidate selection — 0 → unavailable, 1 → handoff, ≥2 → ask
  which (never the first portal picked arbitrarily);
* honesty of presentation (D-R3-6): the authenticated portal is announced as an
  online procedure whose authentication stays with the citizen, never as a
  "downloadable form";
* provenance (D-R3-7): the executed request carries exactly the confirmed
  candidate URL as ``service_id``; no URL is invented;
* I6: no hardcoded municipality fallback — an unknown comune is asked, not
  guessed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from treasureiq.catalog.contracts import AccessMode
from treasureiq.catalog.service_contracts import (
    AuthenticationMethod,
    ServiceAccessMode,
    ServicePortalCandidate,
    ServicePortalRole,
    SourceInventory,
)
from treasureiq.chat import respond
from treasureiq.chat.intent import Topic, TOPIC_KEYWORDS
from treasureiq.chat.respond import _risposta_modulistica, _spid_reason_da_metodi

ISTAT = "058091"
WHEN = datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc)
BASE_URL = "https://www.comune.prova.it"
PORTAL_A = "https://sportello.comune.prova.it/servizi"
PORTAL_B = "https://sportello.comune.prova.it/prenotazioni"


def _candidate(url: str, label: str, methods=(AuthenticationMethod.SPID,)) -> ServicePortalCandidate:
    return ServicePortalCandidate(
        url=url,
        label=label,
        source_url=BASE_URL,
        role=ServicePortalRole.TELEMATICS_DESK,
        access_mode=ServiceAccessMode.AUTHENTICATED_ONLINE,
        platform_id="municipium",
        capabilities=("appointment",),
        authentication=tuple(methods),
        discovered_at=WHEN,
    )


def _inventory(*candidates: ServicePortalCandidate) -> SourceInventory:
    return SourceInventory(
        source_id=ISTAT,
        base_url=BASE_URL,
        service_portals=tuple(candidates),
        updated_at=WHEN,
    )


@pytest.fixture
def stub_inventory(monkeypatch):
    """Inject an inventory both the handler and the default connector read.

    The handler imports ``_inventory_from_live`` at call time and the default
    ``ServicePortalConnettore`` binds it as its loader when the registry is
    built inside the handler — patching the module attribute reaches both.
    """

    def _install(inventory):
        monkeypatch.setattr(
            "treasureiq.catalog.service_portal_connector._inventory_from_live",
            lambda source_id: inventory,
        )
        # No cached MappaConnettore on disk in the test: force the fallback build.
        monkeypatch.setattr(
            "treasureiq.mappa_connettore._da_cache", lambda codice_istat: None
        )

    return _install


def _run(**kwargs):
    return asyncio.run(_risposta_modulistica(**kwargs))


# --- helper: spid_required means "authentication required" (D-R3, vincolo 3) --


def test_auth_reason_lists_present_methods():
    required, reason = _spid_reason_da_metodi(
        [AuthenticationMethod.SPID, AuthenticationMethod.CIE]
    )
    assert required is True
    assert "SPID" in reason and "CIE" in reason


def test_auth_reason_generic_when_only_unknown():
    required, reason = _spid_reason_da_metodi([AuthenticationMethod.UNKNOWN])
    assert required is True
    assert "SPID" not in reason  # no invented method
    assert "autenticazione" in reason.lower()


# --- deterministic selection ------------------------------------------------


def test_zero_candidates_is_unavailable(stub_inventory):
    stub_inventory(None)
    answer = _run(message="serve la modulistica", profile=None, comune_istat=ISTAT)
    assert answer.topic is Topic.MODULISTICA
    assert answer.data_gap == "not_published"
    assert answer.access_mode is None
    assert answer.spid_required is False
    assert answer.info is None


def test_single_candidate_hands_off_to_portal(stub_inventory):
    stub_inventory(_inventory(_candidate(PORTAL_A, "Sportello telematico")))
    answer = _run(message="voglio lo sportello online", profile=None, comune_istat=ISTAT)
    assert answer.access_mode == AccessMode.INDIRECT.value
    assert answer.spid_required is True
    assert answer.info is not None and answer.info.document is not None
    assert answer.info.document.url == PORTAL_A
    assert len(answer.data_batches) == 1
    # Canonical chain: a QueryPlan sits behind the pointer, and the selected
    # batch is the one we executed.
    assert answer.query_plan is not None
    assert answer.selected_data_batch is answer.data_batches[0]


def test_single_candidate_reply_is_online_procedure_not_download(stub_inventory):
    # D-R3-6: never present the authenticated portal as a downloadable form.
    stub_inventory(_inventory(_candidate(PORTAL_A, "Sportello telematico")))
    answer = _run(message="voglio lo sportello online", profile=None, comune_istat=ISTAT)
    testo = answer.reply.lower()
    assert "procedura online" in testo
    assert "scaric" not in testo  # no "scaricabile"/"scarica"
    assert "autenticazione resta a te" in testo or "resta a te" in testo


def test_multiple_candidates_ask_which(stub_inventory):
    stub_inventory(
        _inventory(
            _candidate(PORTAL_A, "Sportello telematico"),
            _candidate(PORTAL_B, "Prenotazioni"),
        )
    )
    answer = _run(message="servizi online", profile=None, comune_istat=ISTAT)
    assert answer.needs_clarification is True
    assert answer.access_mode == AccessMode.INDIRECT.value
    assert answer.info is not None
    urls = {azione.url for azione in answer.info.azioni}
    assert urls == {PORTAL_A, PORTAL_B}  # never picked one arbitrarily


def test_executed_request_carries_confirmed_url(stub_inventory, monkeypatch):
    # D-R3-7: service_id is exactly the confirmed candidate URL.
    stub_inventory(_inventory(_candidate(PORTAL_A, "Sportello telematico")))
    seen = {}
    real = respond.service_portal_request

    def _spy(*, source_id, service_id, **kw):
        seen["service_id"] = service_id
        seen["source_id"] = source_id
        return real(source_id=source_id, service_id=service_id, **kw)

    monkeypatch.setattr(respond, "service_portal_request", _spy)
    _run(message="sportello online", profile=None, comune_istat=ISTAT)
    assert seen["service_id"] == PORTAL_A
    assert seen["source_id"] == ISTAT


# --- I6: no hardcoded fallback ---------------------------------------------


def test_unknown_comune_is_asked_not_guessed(stub_inventory):
    stub_inventory(None)
    answer = _run(message="serve la modulistica", profile=None, comune_istat=None)
    assert answer.data_gap == "comune_non_noto"
    assert answer.needs_clarification is True


# --- topic keyword support (gate) ------------------------------------------


def test_modulistica_has_lexical_support():
    assert "modulistica" in TOPIC_KEYWORDS[Topic.MODULISTICA]
    assert respond._tema_sostenuto(topic=Topic.MODULISTICA, testo="serve la modulistica")
