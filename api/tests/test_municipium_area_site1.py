"""Fix A — la mappa Municipium topic→Area vale anche al drill site-1.

`_office_da_ufficio_nominato` è il drill del rail INFORMAZIONE site-1 (chiamato
sia per l'ufficio nominato sia per la richiesta RESPONSABILE senza ufficio). Prima
consultava solo `_ufficio_connettore_pertinente`: su Ariccia (058009, Municipium)
le macro-Aree non nominano il servizio, così «a chi mi rivolgo per l'anagrafe»
(ufficio_chiesto="") non trovava nulla e ripiegava sul Centralino URP.

La cura riusa la STESSA `_area_municipium_per_topic` del site-2
(`_risposta_da_connettore`): quando il cittadino non ha nominato un ufficio e la
piattaforma è Municipium con Area evidence-locked, il topic deduce la sottostringa
d'Area. Nessuna mappa duplicata. Questi test pinnano il comportamento al drill:
la deduzione scatta dove c'è evidenza, il fallback resta onesto altrove, l'ufficio
esplicitamente nominato vince ancora, e la ServiceKey esclusa (carta d'identità)
non over-reach sull'Area.
"""

from __future__ import annotations

import asyncio

import pytest

import treasureiq.chat.respond as R
from treasureiq.chat.intent import Topic
from treasureiq.connettore import EsitoConnettore, UfficioConnettore
from treasureiq.chat.service_key import ServiceKey
from treasureiq.ufficio_dettaglio import UfficioArricchito

# Ariccia (058009): Aree Municipium che NON nominano il servizio nel titolo.
# La mappa evidence-locked collega ANAGRAFE_CARTA_IDENTITA → «amministrativa».
ARICCIA = "058009"


def _ufficio(nome: str) -> UfficioConnettore:
    return UfficioConnettore(
        nome=nome,
        url="https://comune.ariccia.rm.it/it/uo/" + nome[:8],
        source_typed=False,
        letto_il="2026-08-27T00:00:00+00:00",
    )


def _aree_ariccia() -> list[UfficioConnettore]:
    return [
        _ufficio("Area V – Amministrativa"),
        _ufficio("Area I – Programmazione e Controllo attività economiche e finanziarie"),
        _ufficio("Servizio Tributi Ambiente"),
    ]


def _esito(codice_istat: str, piattaforma: str, uffici) -> EsitoConnettore:
    return EsitoConnettore(
        codice_istat=codice_istat,
        piattaforma=piattaforma,
        uffici=uffici,
        letto_il="2026-08-27T00:00:00+00:00",
    )


def _mock_infra(monkeypatch: pytest.MonkeyPatch, esito: EsitoConnettore) -> None:
    """Isola i due seam del drill: la lettura connettore e l'arricchimento di rete.
    `arricchisci_ufficio` fa da identità (eco dell'ufficio matchato), così l'esito
    del test dipende SOLO da quale Area il match ha scelto."""
    monkeypatch.setattr(R.connettore, "leggi_connettore", lambda codice_istat: esito)
    monkeypatch.setattr(
        R,
        "arricchisci_ufficio",
        lambda *, codice_istat, ufficio, piattaforma=None: UfficioArricchito(
            ufficio=ufficio,
            orari_fonte=None,
            responsabile_ispezionato=False,
        ),
    )


def _drill(codice_istat: str, ufficio_chiesto: str, service_key=None):
    return asyncio.run(
        R._office_da_ufficio_nominato(
            codice_istat=codice_istat,
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            ufficio_chiesto=ufficio_chiesto,
            disabilita_attiva=False,
            service_key=service_key,
        )
    )


# --- Il fix: bare anagrafe deduce l'Area anche al site-1 ---------------------


def test_bare_anagrafe_su_municipium_mappato_risolve_area_v(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«a chi mi rivolgo per l'anagrafe» (ufficio_chiesto="") su Ariccia Municipium:
    il topic deduce «amministrativa» e il drill aggancia l'Area V — non più il
    Centralino URP."""
    _mock_infra(monkeypatch, _esito(ARICCIA, "municipium", _aree_ariccia()))

    res = _drill(ARICCIA, ufficio_chiesto="")

    assert res is not None
    assert res.office.nome == "Area V – Amministrativa"


def test_ufficio_esplicito_vince_sulla_mappa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Se il cittadino nomina un ufficio, la deduzione NON scatta (guardia
    `ufficio_chiesto` in `_area_municipium_per_topic`): «tributi» aggancia il
    Servizio Tributi, non l'Area V dedotta dal topic."""
    _mock_infra(monkeypatch, _esito(ARICCIA, "municipium", _aree_ariccia()))

    res = _drill(ARICCIA, ufficio_chiesto="tributi")

    assert res is not None
    assert res.office.nome == "Servizio Tributi Ambiente"


# --- Il fallback resta onesto: mai un'Area indovinata -----------------------


def test_bare_anagrafe_su_piattaforma_non_municipium_fallback_onesto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stesse Aree ma piattaforma non-Municipium: la mappa non si applica, il
    topic-split «anagrafe» a parola intera non è in nessun nome d'Area →
    nessun ufficio dedotto (l'URP di ripiego resta, D-04)."""
    _mock_infra(monkeypatch, _esito(ARICCIA, "wordpress_agid", _aree_ariccia()))

    res = _drill(ARICCIA, ufficio_chiesto="")

    assert res is None


def test_bare_anagrafe_su_municipium_non_mappato_fallback_onesto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comune Municipium NON in `_MUNICIPIUM_TOPIC_AREA`: nessuna evidenza
    pubblicata → nessuna Area dedotta, fallback onesto."""
    _mock_infra(monkeypatch, _esito("099999", "municipium", _aree_ariccia()))

    res = _drill("099999", ufficio_chiesto="")

    assert res is None


def test_carta_identita_esclusa_non_over_reach_su_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La carta d'identità condivide il Topic accorpato con l'anagrafe ma NON è
    citata dall'Area V: con `ServiceKey.CARTA_IDENTITA` la deduzione è esclusa
    (`_MUNICIPIUM_SERVICE_KEY_ESCLUSE`) → fallback onesto, nessuna Area inventata."""
    _mock_infra(monkeypatch, _esito(ARICCIA, "municipium", _aree_ariccia()))

    res = _drill(ARICCIA, ufficio_chiesto="", service_key=ServiceKey.CARTA_IDENTITA)

    assert res is None
