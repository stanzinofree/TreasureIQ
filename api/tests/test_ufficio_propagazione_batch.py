"""Propagazione dei campi letti dal vivo fino al DataBatch TRASPORTATO (Codex P1).

Il rail INFORMAZIONE coperto (`_risposta_da_connettore`) legge l'ufficio nominato
adesso dalla sua pagina (orari, e dove pubblicati indirizzo/responsabile) e deve
far arrivare quei campi al `DataBatch` che la risposta trasporta — non fermarli
nell'`OfficeAnswer`. La cura: `_orari_ufficio_live` torna l'ufficio ARRICCHITO
intero e la risposta lo sostituisce nell'`EsitoConnettore` PRIMA di proiettare
`data_batches`/`query_plan`/`selected_data_batch`.

Questo test guida la funzione reale end-to-end. Monkeypatcha solo due seam:
- il GATE `_batch_offices_decisione` (decisione MEDIATO/web, testata altrove) →
  forzato MEDIATO su un batch reale, così il rail ufficio parte;
- il boundary di rete `_orari_ufficio_live` → torna l'ufficio arricchito.
La PROIEZIONE resta reale (`_data_batches_da_connettore` gira davvero, su
piattaforma `wordpress_agid` che il manifest proietta in `offices`), così ciò che
si verifica è il batch vero trasportato dalla risposta.
"""

from __future__ import annotations

import asyncio

import pytest

import treasureiq.chat.respond as R
import treasureiq.mappa_connettore as mc
from treasureiq.chat.intent import Topic
from treasureiq.connettore import EsitoConnettore, Responsabile, UfficioConnettore
from treasureiq.mappa_connettore import MappaConnettore

ISTAT = "058003"
URL_UFFICIO = "https://c.example.it/uffici/anagrafe/"


def _ufficio_catalogo() -> UfficioConnettore:
    # Come esce dallo sweep: senza orari/indirizzo/responsabile per-ufficio.
    return UfficioConnettore(
        nome="Ufficio Anagrafe",
        url=URL_UFFICIO,
        telefoni=["06 111"],
        email=["ana@ex.it"],
        pec=[],
        orari=None,
        source_typed=True,
        letto_il="2026-08-12T00:00:00+00:00",
    )


def _esito(uff: UfficioConnettore) -> EsitoConnettore:
    # `wordpress_agid`: il manifest la proietta in una offices batch reale, così
    # `_data_batches_da_connettore` produce il batch che la risposta trasporta.
    return EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma="wordpress_agid",
        uffici=[uff],
        letto_il="2026-08-12T00:00:00+00:00",
    )


def _monkeypatch_infra(monkeypatch: pytest.MonkeyPatch, esito: EsitoConnettore) -> None:
    # Mappa presente: senza, `_data_batches_da_connettore` ripiega su [].
    monkeypatch.setattr(
        mc,
        "_da_cache",
        lambda istat: MappaConnettore(
            codice_istat=istat, nome="X", sito=None, sondato_il=esito.letto_il
        ),
    )
    # Gate MEDIATO da un batch REALE (stesso ufficio, url combaciante), così il
    # rail ufficio parte e `_ufficio_connettore_pertinente` trova la scheda.
    esito_openpa = esito.model_copy(update={"piattaforma": "openpa"})
    gate_batch = R._batch_offices_decisione(esito_openpa, comune_nome="Albano")
    assert gate_batch is not None and gate_batch.records, "setup: gate non MEDIATO"
    monkeypatch.setattr(
        R,
        "_batch_offices_decisione",
        lambda e, *, comune_nome, recognition=None: gate_batch,
    )


def _offices_record(res) -> dict:
    for batch in res.data_batches:
        if batch.capability == "offices":
            assert batch.records, "offices batch senza record"
            return batch.records[0]
    raise AssertionError("nessuna offices batch trasportata dalla risposta")


def test_campi_letti_dal_vivo_entrano_nel_batch_trasportato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    esito = _esito(_ufficio_catalogo())
    _monkeypatch_infra(monkeypatch, esito)

    # Boundary di rete: la pagina pubblica orari + indirizzo + responsabile.
    arricchito = _ufficio_catalogo().model_copy(
        update={
            "orari": "Lun 9-12",
            "indirizzo": "Piazza Roma, 1 - 00041 Albano (RM)",
            "responsabile": Responsabile(nome="Mario Rossi", ruolo="Responsabile"),
        }
    )

    async def _live(*, codice_istat, ufficio, piattaforma=None):
        assert piattaforma == "wordpress_agid"  # la piattaforma è inoltrata
        return arricchito, "lunedì 9-12"

    monkeypatch.setattr(R, "_orari_ufficio_live", _live)

    res = asyncio.run(
        R._risposta_da_connettore(
            comune_nome="Albano",
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            diagnosi=[],
            esito=esito,
            ufficio_chiesto="anagrafe",
            disabilita_attiva=False,
            recognition=None,
        )
    )

    record = _offices_record(res)
    assert record["indirizzo"] == "Piazza Roma, 1 - 00041 Albano (RM)"
    assert record["responsabile"] == {
        "nome": "Mario Rossi",
        "ruolo": "Responsabile",
        "email": None,
    }
    assert record["orari"] == "Lun 9-12"  # anche l'orario letto viaggia nel batch


def test_batch_trasportato_senza_lettura_resta_onesto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Controllo: se la pagina non pubblica i campi, il batch non li inventa —
    # restano None (D-05). Prova che i campi del test sopra vengono DAVVERO
    # dalla lettura sostituita nell'esito, non da un'altra sorgente.
    esito = _esito(_ufficio_catalogo())
    _monkeypatch_infra(monkeypatch, esito)

    async def _live(*, codice_istat, ufficio, piattaforma=None):
        return _ufficio_catalogo(), None  # nessun arricchimento

    monkeypatch.setattr(R, "_orari_ufficio_live", _live)

    res = asyncio.run(
        R._risposta_da_connettore(
            comune_nome="Albano",
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            diagnosi=[],
            esito=esito,
            ufficio_chiesto="anagrafe",
            disabilita_attiva=False,
            recognition=None,
        )
    )

    record = _offices_record(res)
    assert record["indirizzo"] is None
    assert record["responsabile"] is None


# --- La scheda VERDE (`info.office`), non solo il batch trasportato -----------
# I due rami che costruiscono un `OfficeAnswer` devono entrambi portare i campi
# additivi letti dalla scheda (indirizzo, responsabile). Il batch li portava già
# (test sopra); l'`OfficeAnswer` renderizzato — ciò che la UI mostra come scheda
# verde via `OfficeOut` — su un ramo li lasciava cadere. Questi test pinnano il
# surface `info.office` su ENTRAMBI i rami.


def test_office_answer_ramo_connettore_porta_indirizzo_e_responsabile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ramo A (`_risposta_da_connettore`): la scheda verde porta i campi letti."""
    esito = _esito(_ufficio_catalogo())
    _monkeypatch_infra(monkeypatch, esito)

    arricchito = _ufficio_catalogo().model_copy(
        update={
            "orari": "Lun 9-12",
            "indirizzo": "Piazza Roma, 1 - 00041 Albano (RM)",
            "responsabile": Responsabile(nome="Mario Rossi", ruolo="Responsabile"),
        }
    )

    async def _live(*, codice_istat, ufficio, piattaforma=None):
        return arricchito, "lunedì 9-12"

    monkeypatch.setattr(R, "_orari_ufficio_live", _live)

    res = asyncio.run(
        R._risposta_da_connettore(
            comune_nome="Albano",
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            diagnosi=[],
            esito=esito,
            ufficio_chiesto="anagrafe",
            disabilita_attiva=False,
            recognition=None,
        )
    )

    office = res.info.office
    assert office is not None
    assert office.indirizzo == "Piazza Roma, 1 - 00041 Albano (RM)"
    assert office.responsabile is not None
    assert office.responsabile.nome == "Mario Rossi"
    assert office.responsabile.ruolo == "Responsabile"


def test_office_answer_ramo_connettore_onesto_senza_lettura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ramo A, degrado onesto: pagina senza i campi → `None`, mai inventati."""
    esito = _esito(_ufficio_catalogo())
    _monkeypatch_infra(monkeypatch, esito)

    async def _live(*, codice_istat, ufficio, piattaforma=None):
        return _ufficio_catalogo(), None

    monkeypatch.setattr(R, "_orari_ufficio_live", _live)

    res = asyncio.run(
        R._risposta_da_connettore(
            comune_nome="Albano",
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            diagnosi=[],
            esito=esito,
            ufficio_chiesto="anagrafe",
            disabilita_attiva=False,
            recognition=None,
        )
    )

    office = res.info.office
    assert office is not None
    assert office.indirizzo is None
    assert office.responsabile is None


def test_office_answer_ramo_nominato_porta_indirizzo_e_responsabile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ramo B (`_office_da_ufficio_nominato`): il drill già consegnava i campi —
    lo pinniamo perché resti simmetrico al ramo A."""
    from treasureiq.ufficio_dettaglio import UfficioArricchito

    esito = _esito(_ufficio_catalogo())
    arricchito = _ufficio_catalogo().model_copy(
        update={
            "orari": "Lun 9-12",
            "indirizzo": "Via Garibaldi, 3 - 00041 Albano (RM)",
            "responsabile": Responsabile(nome="Lucia Bianchi", ruolo="Dirigente"),
        }
    )

    monkeypatch.setattr(
        R.connettore, "leggi_connettore", lambda codice_istat: esito
    )
    monkeypatch.setattr(
        R,
        "arricchisci_ufficio",
        lambda *, codice_istat, ufficio, piattaforma=None: UfficioArricchito(
            ufficio=arricchito, orari_fonte="lunedì 9-12"
        ),
    )

    res = asyncio.run(
        R._office_da_ufficio_nominato(
            codice_istat=ISTAT,
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            ufficio_chiesto="anagrafe",
            disabilita_attiva=False,
        )
    )

    assert res is not None
    office = res.office
    assert office.indirizzo == "Via Garibaldi, 3 - 00041 Albano (RM)"
    assert office.responsabile is not None
    assert office.responsabile.nome == "Lucia Bianchi"
    assert office.responsabile.ruolo == "Dirigente"
