"""Ramo 3 — Modulistica chat wiring through the resolver (Slice 5, §5).

Pin the NEW behaviour: Topic.MODULISTICA reaches the real WP/AgID resolver
(no network here — ``resolve_service_with_meta`` is stubbed at the module seam)
and produces a MEDIATED DataBatch + ``InfoAnswer.service`` that keeps the
information page, the downloadable form and the online procedure distinct.

The central invariant (D-S5-2): a resolver miss — unknown platform, no connector,
0/≥2 confirmed, unreachable — answers honestly (ask comune / URP redirect) and
NEVER falls back to the old SP pointer. Plus: 0/≥2 service keys → ask which
pratica (no fetch); unknown comune → ask (I6).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from treasureiq.catalog.contracts import AccessMode, ConnectorRef
from treasureiq.catalog.service_contracts import (
    AuthenticationMethod,
    ResolvedService,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceReference,
)
from treasureiq.chat import respond
from treasureiq.chat.intent import Topic, TOPIC_KEYWORDS
from treasureiq.chat.respond import _risposta_modulistica, _spid_reason_da_metodi
from treasureiq.mappa_connettore import MappaConnettore

ISTAT = "058091"
WHEN = datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc)
BASE_URL = "https://www.comune.prova.it"
CONN = ConnectorRef(name="wordpress_agid_service", version="1")


def _mappa(*, piattaforma_id: str | None = "wordpress_agid") -> MappaConnettore:
    return MappaConnettore(
        codice_istat=ISTAT,
        nome="Prova",
        sito=BASE_URL,
        sondato_il="2026-08-22T09:00:00+00:00",
        piattaforma_id=piattaforma_id,
    )


def _reference(*, con_auth: bool = False) -> ServiceReference:
    options = [
        ServiceAccessOption(
            mode=ServiceAccessMode.INFORMATION,
            url=f"{BASE_URL}/servizi/cie",
        ),
        ServiceAccessOption(
            mode=ServiceAccessMode.DOWNLOAD,
            url=f"{BASE_URL}/servizi/cie/modulo.pdf",
        ),
    ]
    if con_auth:
        options.append(
            ServiceAccessOption(
                mode=ServiceAccessMode.AUTHENTICATED_ONLINE,
                url="https://portale.prova.it/cie",
                authentication=(AuthenticationMethod.SPID,),
                requires_authentication=True,
            )
        )
    return ServiceReference(
        service_id=f"{ISTAT}:wp:42",
        title="Carta d'identità elettronica",
        source_url=f"{BASE_URL}/servizi/cie",
        options=tuple(options),
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _resolved(reference: ServiceReference, *, from_cache: bool = False) -> ResolvedService:
    return ResolvedService(
        reference=reference,
        retrieved_at=WHEN,
        from_cache=from_cache,
        connector=CONN,
    )


@pytest.fixture
def wiring(monkeypatch):
    """Patch the two seams the handler crosses: the cached mappa and the resolver.

    ``_da_cache`` is imported inside the handler → patch the module attribute.
    ``resolve_service_with_meta`` is a module-level import in ``respond``. A spy
    records whether the resolver was called at all (0/≥2 keys must not fetch).
    """
    stato = {"chiamate": 0, "resolved": None, "mappa": _mappa()}

    def _da_cache(codice_istat):
        return stato["mappa"]

    def _resolver(request, **kw):
        stato["chiamate"] += 1
        return stato["resolved"]

    monkeypatch.setattr("treasureiq.mappa_connettore._da_cache", _da_cache)
    monkeypatch.setattr(respond, "resolve_service_with_meta", _resolver)
    return stato


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


# --- happy path: resolver returns a reference ------------------------------


def test_servizio_risolto_mediated_con_download(wiring):
    wiring["mappa"] = _mappa()
    wiring["resolved"] = _resolved(_reference())
    answer = _run(message="modulo della carta d'identità", profile=None, comune_istat=ISTAT)
    assert answer.topic is Topic.MODULISTICA
    assert answer.data_gap is None
    assert answer.needs_clarification is False
    assert answer.access_mode == AccessMode.MEDIATED.value
    assert len(answer.data_batches) == 1
    assert answer.query_plan is not None
    assert answer.selected_data_batch is answer.data_batches[0]
    # InfoAnswer.service keeps the options distinct: a download is present.
    assert answer.info is not None and answer.info.service is not None
    assert len(answer.info.service.downloads) == 1
    assert answer.info.service.information is not None
    # pure-download/information service does not require authentication
    assert answer.spid_required is False


def test_procedura_online_richiede_auth_non_download(wiring):
    # D-R3-6: an AUTHENTICATED_ONLINE option is a procedure the citizen runs, not
    # a form TIQ downloads/fills.
    wiring["mappa"] = _mappa()
    wiring["resolved"] = _resolved(_reference(con_auth=True))
    answer = _run(message="modulo della carta d'identità", profile=None, comune_istat=ISTAT)
    assert answer.spid_required is True
    assert answer.spid_reason is not None and "SPID" in answer.spid_reason
    assert len(answer.info.service.authenticated_online) == 1
    assert "non accedo né compilo" in answer.reply.lower()


# --- honest misses: NEVER the SP pointer (D-S5-2) --------------------------


def test_service_key_ambigua_chiede_senza_fetch(wiring):
    # 0 keys → ask which pratica, and the resolver is NOT called.
    wiring["mappa"] = _mappa()
    answer = _run(message="serve la modulistica", profile=None, comune_istat=ISTAT)
    assert answer.needs_clarification is True
    assert answer.info is None
    assert answer.access_mode is None
    assert wiring["chiamate"] == 0


def test_tributo_generico_chiede_imu_o_tari_senza_fetch(wiring):
    # D3: generic tax intent ("tasse"), no specific tax → after the split there
    # is no generic key; the dispatcher asks WHICH tax, never resolves. No fetch.
    wiring["mappa"] = _mappa()
    answer = _run(message="devo pagare le tasse comunali", profile=None, comune_istat=ISTAT)
    assert answer.needs_clarification is True
    assert answer.data_gap == "tributo_non_specificato"
    assert "IMU" in answer.reply and "TARI" in answer.reply
    assert answer.info is None
    assert answer.access_mode is None
    assert wiring["chiamate"] == 0


def test_tributi_generico_bare_word_chiede_imu_o_tari(wiring):
    # The bare word "tributi" (dropped as a recogniser marker) still routes to
    # the IMU/TARI clarification at the dispatcher, not to a fabricated key.
    wiring["mappa"] = _mappa()
    answer = _run(message="modulo per i tributi", profile=None, comune_istat=ISTAT)
    assert answer.needs_clarification is True
    assert answer.data_gap == "tributo_non_specificato"
    assert "IMU" in answer.reply and "TARI" in answer.reply
    assert wiring["chiamate"] == 0


def test_contributi_non_e_tributo_lista_generica(wiring):
    # "contributi" (grants) must NOT trigger the tax clarification: whole-word
    # guard. It falls through to the generic vocabulary list (data_gap None).
    wiring["mappa"] = _mappa()
    answer = _run(message="vorrei un contributo per l'affitto", profile=None, comune_istat=ISTAT)
    assert answer.needs_clarification is True
    # The generic branch (not the tax one): its own data_gap and the full
    # vocabulary list, not the "which tax?" prompt.
    assert answer.data_gap is None
    assert "carta d'identità" in answer.reply
    assert wiring["chiamate"] == 0


def test_piattaforma_assente_miss_urp_senza_sp(wiring):
    wiring["mappa"] = _mappa(piattaforma_id=None)
    answer = _run(message="modulo della carta d'identità", profile=None, comune_istat=ISTAT)
    assert answer.data_gap == "not_verified"
    assert answer.access_mode is None
    assert answer.info is None
    assert answer.needs_clarification is False
    assert wiring["chiamate"] == 0  # no platform → no resolver call


def test_mappa_assente_miss_urp(wiring):
    wiring["mappa"] = None
    answer = _run(message="modulo della carta d'identità", profile=None, comune_istat=ISTAT)
    assert answer.data_gap == "not_verified"
    assert answer.info is None


def test_resolver_miss_urp_niente_sp(wiring):
    wiring["mappa"] = _mappa()
    wiring["resolved"] = None  # connector 0/≥2 confirmed / unreachable
    answer = _run(message="modulo della carta d'identità", profile=None, comune_istat=ISTAT)
    assert wiring["chiamate"] == 1
    assert answer.data_gap == "not_verified"
    assert answer.access_mode is None
    assert answer.info is None


# --- I6: no hardcoded fallback ---------------------------------------------


def test_unknown_comune_is_asked_not_guessed(wiring):
    answer = _run(message="modulo della carta d'identità", profile=None, comune_istat=None)
    assert answer.data_gap == "comune_non_noto"
    assert answer.needs_clarification is True
    assert wiring["chiamate"] == 0


# --- topic keyword support (gate) ------------------------------------------


def test_modulistica_has_lexical_support():
    assert "modulistica" in TOPIC_KEYWORDS[Topic.MODULISTICA]
    assert respond._tema_sostenuto(topic=Topic.MODULISTICA, testo="serve la modulistica")


# --- Fix A (Slice 5.2): precedenza deterministica del MODULO sul contenuto ---


@pytest.mark.parametrize(
    "messaggio",
    [
        "modulo carta d'identità",
        "modulo della carta d'identità",
        "dov'è la modulistica anagrafe",
        "cerco il formulario per il cambio residenza",
        "il documento è scaricabile?",
    ],
)
def test_richiesta_modulo_ha_precedenza(messaggio):
    # La parola-modulo instrada a MODULISTICA anche quando il testo porta la
    # keyword forte di un topic di contenuto (qui «carta d'identità»/«anagrafe»).
    assert respond._richiesta_modulo(messaggio) is True


@pytest.mark.parametrize(
    "messaggio",
    [
        "orari ufficio anagrafe",
        "come rinnovo la carta d'identità",
        "quanto costa la carta d'identità",
    ],
)
def test_senza_parola_modulo_resta_sul_contenuto(messaggio):
    # Nessun marcatore-modulo → il topic di contenuto NON viene scavalcato
    # (l'override in dispatch non scatta). Il rinnovo resta anagrafe salvo
    # richiesta esplicita di modulo.
    assert respond._richiesta_modulo(messaggio) is False


def test_marcatori_precedenza_sono_gate_coerenti():
    # Ogni marcatore che scavalca il contenuto deve reggere anche il gate
    # lessicale del ramo (`_tema_sostenuto`), altrimenti l'override porterebbe a
    # MODULISTICA un turno che poi il gate scarterebbe: instradamento a vuoto.
    for marcatore in respond._MARCATORI_PRECEDENZA_MODULISTICA:
        assert marcatore in TOPIC_KEYWORDS[Topic.MODULISTICA]
        assert respond._tema_sostenuto(topic=Topic.MODULISTICA, testo=f"serve {marcatore}")
