"""Slice informativo-azionabile → catalogo.

Una richiesta informativa per FORMA ma azionabile per intento — «come rinnovo
la carta d'identità?», «voglio cambiare residenza» — deve consultare il
catalogo servizi (stesso `_risposta_modulistica`, zero fetch) quando il comune
ha un catalogo. Una domanda-dato («quanto pago l'IMU?»), una chiave fuori
ambito, o un comune senza catalogo restano sul rail informazione invariato.

Due livelli:
1. Detector puro `_richiesta_servizio_azionabile` (whitelist chiusa di cornici
   procedurali, nessun modello).
2. Il ramo dispatcher in `build_chat_answer`: il catalogo è consultato SOLO nel
   primo gruppo, e il routing Municipium/WP non cambia.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest import mock

import pytest

from treasureiq.catalog import (
    AccessMode,
    AgidCompatibility,
    MunicipalityPlatformSnapshot,
    SnapshotStore,
    Surface,
)
from treasureiq.chat import respond as respond_mod
from treasureiq.chat.intent import ChatIntent, QuestionKind, Topic
from treasureiq.chat.respond import ChatAnswer

# --- 1. Detector puro --------------------------------------------------------


@pytest.mark.parametrize(
    "messaggio",
    [
        "come richiedo la carta d'identità?",
        "come rinnovo la carta",
        "come ottengo la residenza",
        "come faccio per cambiare residenza",
        "come cambio residenza",
        "voglio cambiare residenza",
        "vorrei rinnovare la carta",
        "devo rifare la carta d'identità",
    ],
)
def test_cornice_azionabile_riconosciuta(messaggio):
    assert respond_mod._richiesta_servizio_azionabile(messaggio) is True


@pytest.mark.parametrize(
    "messaggio",
    [
        "quanto pago l'IMU?",
        "quando scade la carta d'identità",
        "dove si trova l'anagrafe",
        "quali documenti servono per la residenza",
        "a chi mi rivolgo per l'anagrafe",
        "costo della carta d'identità",
    ],
)
def test_domanda_informativa_non_e_azionabile(messaggio):
    assert respond_mod._richiesta_servizio_azionabile(messaggio) is False


# --- 2. Ramo dispatcher ------------------------------------------------------

_COMUNE_CON_CATALOGO = "058003"
_COMUNE_SENZA_CATALOGO = "058003"


def _snapshot(codice_istat: str) -> MunicipalityPlatformSnapshot:
    return MunicipalityPlatformSnapshot(
        municipality_istat=codice_istat,
        surface=Surface.ORDINARY_DATA,
        platform_id="wp_design_comuni",
        platform_compatibility=AgidCompatibility.PARTIAL,
        access_mode=AccessMode.MEDIATED,
        measured_at=datetime.now(timezone.utc),
        measurement_id="sweep-1",
    )


def _modello(intento: ChatIntent):
    class _ModelloFinto:
        async def aparse(self, *, system, user, output_model):
            return intento

    return _ModelloFinto()


def _guida_build(
    *, message: str, intento: ChatIntent, comune_istat: str
):
    """Guida `build_chat_answer` con provider finto e catalogo opzionale,
    spiando `_risposta_modulistica`. Ritorna lo spy per l'asserzione.

    Lo spy restituisce un `ChatAnswer` minimo perché `build_chat_answer`
    post-processa l'esito con `replace(...)`; l'asserzione è comunque SE
    `_risposta_modulistica` viene chiamato, non cosa restituisce."""
    sentinella = ChatAnswer(
        reply="[modulistica]",
        topic=Topic.MODULISTICA,
        kind=QuestionKind.INFORMAZIONE,
        data_gap=None,
        needs_clarification=False,
        matches=[],
        spid_required=False,
        spid_reason=None,
    )
    spia = mock.AsyncMock(return_value=sentinella)
    with mock.patch.object(respond_mod, "load_provider", lambda **_: _modello(intento)):
        with mock.patch.object(respond_mod, "_risposta_modulistica", spia):
            asyncio.run(
                respond_mod.build_chat_answer(
                    message=message,
                    profile=None,
                    records=[],
                    comune_istat=comune_istat,
                )
            )
    return spia


@pytest.fixture()
def catalogo_tmp(monkeypatch, tmp_path):
    """Installa un catalogo per `_COMUNE_CON_CATALOGO` in una DATA_DIR tmp."""
    store = SnapshotStore(tmp_path / "catalog")
    store.save_municipality(_snapshot(_COMUNE_CON_CATALOGO))
    monkeypatch.setattr(respond_mod, "DATA_DIR", tmp_path)
    return tmp_path


def test_carta_azionabile_con_catalogo_consulta_modulistica(catalogo_tmp):
    intento = ChatIntent(
        topic=Topic.SCONOSCIUTO, kind=QuestionKind.INFORMAZIONE
    )
    spia = _guida_build(
        message="come rinnovo la carta d'identità?",
        intento=intento,
        comune_istat=_COMUNE_CON_CATALOGO,
    )
    assert spia.await_count == 1


def test_residenza_azionabile_con_catalogo_consulta_modulistica(catalogo_tmp):
    intento = ChatIntent(
        topic=Topic.SCONOSCIUTO, kind=QuestionKind.INFORMAZIONE
    )
    spia = _guida_build(
        message="voglio cambiare residenza",
        intento=intento,
        comune_istat=_COMUNE_CON_CATALOGO,
    )
    assert spia.await_count == 1


def test_domanda_informativa_non_consulta_catalogo(catalogo_tmp):
    """«quanto pago l'IMU?» è informativa (nessuna cornice azionabile) e la
    chiave è comunque fuori ambito: il catalogo NON viene consultato."""
    intento = ChatIntent(
        topic=Topic.SCONOSCIUTO, kind=QuestionKind.INFORMAZIONE
    )
    spia = _guida_build(
        message="quanto pago l'IMU?",
        intento=intento,
        comune_istat=_COMUNE_CON_CATALOGO,
    )
    assert spia.await_count == 0


def test_chiave_fuori_ambito_non_consulta_catalogo(catalogo_tmp):
    """Cornice azionabile ma chiave ≠ {carta, residenza}: fuori dallo scope
    della slice, il catalogo non viene forzato."""
    intento = ChatIntent(
        topic=Topic.SCONOSCIUTO, kind=QuestionKind.INFORMAZIONE
    )
    spia = _guida_build(
        message="come richiedo l'accesso agli atti",
        intento=intento,
        comune_istat=_COMUNE_CON_CATALOGO,
    )
    assert spia.await_count == 0


def test_senza_catalogo_non_consulta_modulistica(monkeypatch, tmp_path):
    """Stessa richiesta azionabile ma comune SENZA catalogo: il pre-gate
    `_catalog_access_mode is None` salta il ramo, routing informativo invariato
    (protegge Municipium/WP)."""
    monkeypatch.setattr(respond_mod, "DATA_DIR", tmp_path)
    intento = ChatIntent(
        topic=Topic.SCONOSCIUTO, kind=QuestionKind.INFORMAZIONE
    )
    spia = _guida_build(
        message="come rinnovo la carta d'identità?",
        intento=intento,
        comune_istat=_COMUNE_SENZA_CATALOGO,
    )
    assert spia.await_count == 0
