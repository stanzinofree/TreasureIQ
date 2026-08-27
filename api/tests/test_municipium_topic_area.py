"""Municipium: mappa topic → macro-Area competente (per-ISTAT, evidence-locked).

Municipium pubblica gli uffici come macro-Aree il cui nome non nomina il
servizio: a Ariccia (058009) l'anagrafe e lo stato civile vivono in «Area V –
Amministrativa», i tributi in «Area I – …finanziarie». Il match diretto
per-topic (`_ufficio_connettore_pertinente` cerca «anagrafe» nei nomi d'Area)
non aggancia nulla → il drill ripiega su Centralino, come misurato in prod.

`_area_municipium_per_topic` chiude il buco SOLO dove la pagina dell'Area
pubblica quel servizio nelle competenze (recon read-only). Il criterio-successo
è non trasformare una macro-Area generica in un falso «Ufficio Anagrafe»:
questi test bloccano le due regressioni simmetriche — la mappa che non aggancia
(buco riaperto) e la mappa che aggancia dove non c'è evidenza (Area inventata).
"""

from __future__ import annotations

import pytest

from treasureiq.chat.intent import Topic
from treasureiq.chat.respond import (
    _area_municipium_per_topic,
    _ufficio_connettore_pertinente,
)
from treasureiq.connettore import UfficioConnettore

ARICCIA = "058009"


def _ufficio(nome: str) -> UfficioConnettore:
    return UfficioConnettore(
        nome=nome,
        url="https://www.comune.ariccia.rm.it/it/uo/" + nome[:8],
        source_typed=False,
        letto_il="2026-08-27T00:00:00+00:00",
    )


# Le macro-Aree realmente pubblicate da Ariccia (recon 27 ago). Nessuna nomina
# «anagrafe»/«tributi»: è il punto per cui serve la mappa.
def _aree_ariccia() -> list[UfficioConnettore]:
    return [
        _ufficio("Consiglio Comunale"),
        _ufficio("Giunta Comunale"),
        _ufficio("Area I – Programmazione e Controllo attività economiche e finanziarie"),
        _ufficio("Area II – Lavori Pubblici e politiche territoriali"),
        _ufficio("Area III - Polizia Locale"),
        _ufficio("Area IV – Protezione civile e servizi al territorio"),
        _ufficio("Area V – Amministrativa"),
    ]


# --- La mappa: topic → sottostringa d'Area, solo con evidenza ---
@pytest.mark.parametrize(
    "topic, atteso",
    [
        (Topic.ANAGRAFE_CARTA_IDENTITA, "amministrativa"),  # Area V pubblica «Anagrafe»
        (Topic.MATRIMONIO_SEPARAZIONE, "amministrativa"),  # Area V pubblica «Stato Civile»
        (Topic.TRIBUTI, "finanziari"),  # Area I pubblica «Servizio Tributi»
    ],
)
def test_mappa_aggancia_dove_c_e_evidenza(topic, atteso):
    assert (
        _area_municipium_per_topic(
            codice_istat=ARICCIA, piattaforma="municipium", topic=topic, ufficio_chiesto=None
        )
        == atteso
    )


def test_accesso_atti_non_ha_area_dimostrata_resta_fallback():
    """Ariccia non pubblica un'Area «accesso agli atti»: nessuna voce, il
    chiamante mantiene il fallback onesto (Centralino), non inventa un'Area."""
    assert (
        _area_municipium_per_topic(
            codice_istat=ARICCIA,
            piattaforma="municipium",
            topic=Topic.ACCESSO_ATTI,
            ufficio_chiesto=None,
        )
        is None
    )


def test_topic_sconosciuto_non_inventa_area():
    assert (
        _area_municipium_per_topic(
            codice_istat=ARICCIA,
            piattaforma="municipium",
            topic=Topic.SCONOSCIUTO,
            ufficio_chiesto=None,
        )
        is None
    )


@pytest.mark.parametrize("piattaforma", ["openpa", "wordpress_agid", "egov", None])
def test_mappa_non_tocca_altre_piattaforme(piattaforma):
    """Regressione Albano/OpenPA: la mappa è Municipium-only. Su ogni altra
    piattaforma torna `None` e il routing esistente resta identico."""
    assert (
        _area_municipium_per_topic(
            codice_istat=ARICCIA,
            piattaforma=piattaforma,
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            ufficio_chiesto=None,
        )
        is None
    )


def test_comune_municipium_non_mappato_resta_fallback():
    """Un Municipium non ancora verificato non riceve una mappa a indovinare:
    finché la recon non conferma le sue Aree, resta Centralino."""
    assert (
        _area_municipium_per_topic(
            codice_istat="099999",
            piattaforma="municipium",
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            ufficio_chiesto=None,
        )
        is None
    )


def test_ufficio_gia_nominato_non_viene_sovrascritto():
    """Se il cittadino ha nominato un ufficio, la mappa non interviene: il suo
    testo vince, la deduzione da topic è solo il ripiego quando non nomina."""
    assert (
        _area_municipium_per_topic(
            codice_istat=ARICCIA,
            piattaforma="municipium",
            topic=Topic.TRIBUTI,
            ufficio_chiesto="tributi",
        )
        is None
    )


# --- Il token mappato risolve davvero l'Area giusta nel match ---
def test_token_mappato_risolve_l_area_giusta():
    aree = _aree_ariccia()
    ufficio, ambigui = _ufficio_connettore_pertinente(
        aree,
        ufficio_chiesto="amministrativa",
        topic=Topic.ANAGRAFE_CARTA_IDENTITA,
        disabilita_attiva=False,
    )
    assert ufficio is not None
    assert ufficio.nome == "Area V – Amministrativa"
    assert ambigui == []  # univoco: nessun'altra Area contiene «amministrativa»

    ufficio_trib, _ = _ufficio_connettore_pertinente(
        aree, ufficio_chiesto="finanziari", topic=Topic.TRIBUTI, disabilita_attiva=False
    )
    assert ufficio_trib is not None
    assert ufficio_trib.nome.startswith("Area I")


def test_senza_mappa_il_match_diretto_fallisce():
    """La prova che la mappa serve: col solo topic (nessun `ufficio_chiesto`)
    l'anagrafe non aggancia nessuna Area — il nome «Area V – Amministrativa»
    non contiene «anagrafe» — e il drill cadrebbe su Centralino."""
    ufficio, _ = _ufficio_connettore_pertinente(
        _aree_ariccia(),
        ufficio_chiesto="",
        topic=Topic.ANAGRAFE_CARTA_IDENTITA,
        disabilita_attiva=False,
    )
    assert ufficio is None
