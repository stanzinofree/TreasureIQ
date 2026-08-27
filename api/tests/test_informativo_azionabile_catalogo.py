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
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from treasureiq.catalog.service_contracts import (
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
    ServiceReference,
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


def _service_ref(service_id: str) -> ServiceReference:
    return ServiceReference(
        service_id=service_id,
        title="Servizio",
        source_url="https://comune.example.it/servizio",
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION,
                url="https://comune.example.it/servizio",
            ),
        ),
        discovered_at=datetime.now(timezone.utc),
    )


def _scrivi_catalogo_flat(
    base: Path, codice_istat: str, chiavi: tuple[ServiceKey, ...]
) -> None:
    """Scrive un catalogo flat `{base}/catalog/{istat}.json` con SOLO le chiavi
    date (schema `{municipality_istat, services}`, come il catalogo promosso).

    Il gate della slice legge PROPRIO questo (`service_catalog.carica`), non lo
    snapshot piattaforma: il pre-gate è per-chiave, quindi una chiave assente da
    `chiavi` non è nel file e la voce risulta None."""
    directory = base / "catalog"
    directory.mkdir(parents=True, exist_ok=True)
    services = {
        chiave.value: json.loads(
            _service_ref(f"{codice_istat}:openpa:{indice}").model_dump_json()
        )
        for indice, chiave in enumerate(chiavi)
    }
    (directory / f"{codice_istat}.json").write_text(
        json.dumps({"municipality_istat": codice_istat, "services": services}),
        encoding="utf-8",
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
    """Catalogo flat per `_COMUNE_CON_CATALOGO` (carta + residenza) in una
    DATA_DIR tmp.

    Il gate della slice legge il catalogo flat via `service_catalog.carica`, che
    risolve `catalog_dir()` dall'env `TREASUREIQ_DATA_DIR`. Scriviamo entrambe le
    chiavi in-ambito così i due casi «hit esatto» passano; l'assenza di una
    chiave si prova in un test dedicato con un catalogo di sole `carta`."""
    _scrivi_catalogo_flat(
        tmp_path,
        _COMUNE_CON_CATALOGO,
        (ServiceKey.CARTA_IDENTITA, ServiceKey.CAMBIO_RESIDENZA),
    )
    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))
    return tmp_path


def test_carta_azionabile_con_catalogo_consulta_modulistica(catalogo_tmp):
    # Hit esatto: cornice azionabile + carta ammessa + voce carta nel flat.
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
    # Hit esatto sul caso 001076: la residenza informativa/verbale ora raggiunge
    # il catalogo perché la voce `cambio_residenza` È nel flat.
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
    della slice, il catalogo non viene forzato (guardia sulla ServiceKey)."""
    intento = ChatIntent(
        topic=Topic.SCONOSCIUTO, kind=QuestionKind.INFORMAZIONE
    )
    spia = _guida_build(
        message="come richiedo l'accesso agli atti",
        intento=intento,
        comune_istat=_COMUNE_CON_CATALOGO,
    )
    assert spia.await_count == 0


def test_chiave_in_ambito_ma_assente_dal_flat_non_consulta(monkeypatch, tmp_path):
    """Gate PER-CHIAVE: cornice azionabile + chiave ammessa (residenza), ma la
    voce NON è nel catalogo flat di quel comune (qui il flat ha solo `carta`).
    `service_catalog.carica` → None → ramo saltato, nessuna modulistica forzata.
    È il caso «una chiave assente non forza la modulistica»."""
    _scrivi_catalogo_flat(tmp_path, _COMUNE_CON_CATALOGO, (ServiceKey.CARTA_IDENTITA,))
    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))
    intento = ChatIntent(
        topic=Topic.SCONOSCIUTO, kind=QuestionKind.INFORMAZIONE
    )
    spia = _guida_build(
        message="voglio cambiare residenza",
        intento=intento,
        comune_istat=_COMUNE_CON_CATALOGO,
    )
    assert spia.await_count == 0


def test_senza_catalogo_non_consulta_modulistica(monkeypatch, tmp_path):
    """Comune SENZA file catalogo (DATA_DIR tmp vuota): `service_catalog.carica`
    → None → il pre-gate salta il ramo, routing informativo invariato
    (protegge Municipium/WP e i comuni non coperti)."""
    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))
    intento = ChatIntent(
        topic=Topic.SCONOSCIUTO, kind=QuestionKind.INFORMAZIONE
    )
    spia = _guida_build(
        message="come rinnovo la carta d'identità?",
        intento=intento,
        comune_istat=_COMUNE_SENZA_CATALOGO,
    )
    assert spia.await_count == 0
