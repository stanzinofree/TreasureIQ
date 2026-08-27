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

Granularità: la mappa è keyed per Topic, ma il Topic `ANAGRAFE_CARTA_IDENTITA`
accorpa anagrafe e carta d'identità. La pagina Area V pubblica «Anagrafe» (e
stato civile, residenza), NON «carta d'identità»/«CIE»: la carta d'identità
esplicita è esclusa alla granularità ServiceKey (`_MUNICIPIUM_SERVICE_KEY_ESCLUSE`)
per non ereditare un'evidenza che la pagina non cita.
"""

from __future__ import annotations

import pytest

from treasureiq.chat.intent import Topic
from treasureiq.chat.respond import (
    _area_municipium_per_topic,
    _ufficio_connettore_pertinente,
)
from treasureiq.chat.service_key import ServiceKey
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


def _area(topic: Topic, service_key: ServiceKey | None = None) -> str | None:
    return _area_municipium_per_topic(
        codice_istat=ARICCIA,
        piattaforma="municipium",
        topic=topic,
        ufficio_chiesto=None,
        service_key=service_key,
    )


# --- La mappa aggancia dove c'è evidenza esplicita ---
@pytest.mark.parametrize(
    "topic, service_key, atteso",
    [
        # anagrafe bare (nessuna ServiceKey fine) → Area V: la pagina cita «Anagrafe»
        (Topic.ANAGRAFE_CARTA_IDENTITA, None, "amministrativa"),
        # cambio residenza → stessa Area V (residenza è competenza dell'Area V)
        (Topic.ANAGRAFE_CARTA_IDENTITA, ServiceKey.CAMBIO_RESIDENZA, "amministrativa"),
        # stato civile → Area V, sia che il turno resti sul topic anagrafico...
        (Topic.ANAGRAFE_CARTA_IDENTITA, ServiceKey.STATO_CIVILE, "amministrativa"),
        # ...sia che il modello lo classifichi come matrimonio/stato civile
        (Topic.MATRIMONIO_SEPARAZIONE, ServiceKey.STATO_CIVILE, "amministrativa"),
        (Topic.MATRIMONIO_SEPARAZIONE, None, "amministrativa"),
        # tributi IMU/TARI → Area I (la pagina cita «Servizio Tributi»)
        (Topic.TRIBUTI, ServiceKey.TRIBUTI_IMU, "finanziari"),
        (Topic.TRIBUTI, ServiceKey.TRIBUTI_TARI, "finanziari"),
        (Topic.TRIBUTI, None, "finanziari"),
    ],
)
def test_mappa_aggancia_dove_c_e_evidenza(topic, service_key, atteso):
    assert _area(topic, service_key) == atteso


# --- Carta d'identità: esclusa finché la pagina non cita CIE/carta d'identità ---
def test_carta_identita_esplicita_resta_fallback():
    """La carta d'identità condivide il Topic `ANAGRAFE_CARTA_IDENTITA` con
    l'anagrafe, ma l'Area V pubblica «Anagrafe», non «carta d'identità»/«CIE».
    La ServiceKey esplicita (marker «carta d'identità»/«cie») NON eredita
    l'evidenza dell'anagrafe: cade al fallback onesto (Centralino)."""
    assert _area(Topic.ANAGRAFE_CARTA_IDENTITA, ServiceKey.CARTA_IDENTITA) is None


def test_anagrafe_bare_non_e_toccata_dall_esclusione():
    """L'esclusione morde solo la ServiceKey `CARTA_IDENTITA`: l'anagrafe senza
    ServiceKey fine resta agganciata all'Area V (non un effetto collaterale)."""
    assert _area(Topic.ANAGRAFE_CARTA_IDENTITA, None) == "amministrativa"


# --- Assenza di evidenza → nessuna Area inventata ---
def test_accesso_atti_non_ha_area_dimostrata_resta_fallback():
    """Ariccia non pubblica un'Area «accesso agli atti»: né il Topic né la
    ServiceKey agganciano, il chiamante mantiene il fallback onesto (Centralino)."""
    assert _area(Topic.ACCESSO_ATTI, ServiceKey.ACCESSO_ATTI) is None
    assert _area(Topic.ACCESSO_ATTI, None) is None


def test_topic_sconosciuto_non_inventa_area():
    assert _area(Topic.SCONOSCIUTO, None) is None


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
            service_key=None,
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
            service_key=None,
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
            service_key=ServiceKey.TRIBUTI_IMU,
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
