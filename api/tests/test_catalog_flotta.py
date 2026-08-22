"""Fleet connectors (municipium/comweb/peopleweb × BASE/AT): parity with v0.

Each unit is one (platform × surface) pair, independently named and versioned.
These tests pin three things:

* the units resolve ahead of the wildcard scrape fallback for their platforms;
* the v1 batch carries exactly the offices/contacts/transparency the v0 connector
  rail already surfaces (same record shapes the WordPress adapter emits);
* an absent capability collapses to UNAVAILABLE / NOT_SUPPORTED, the way the v0
  office rail treats an empty ``uffici``.
"""

from __future__ import annotations

import pytest

from treasureiq.catalog.adapters.defaults import default_adapter_registry
from treasureiq.catalog.connector_defaults import default_connector_registry
from treasureiq.catalog.contracts import AccessMode, Surface
from treasureiq.catalog.data_contracts import (
    DataRequest,
    DataStatus,
    FreshnessPolicy,
)
from treasureiq.catalog.flotta import flotta_connectors
from treasureiq.catalog.runtime import CatalogRuntime
from treasureiq.connettore import (
    AmministrazioneTrasparente,
    BandoAT,
    EsitoConnettore,
    Responsabile,
    UfficioConnettore,
)
from treasureiq.mappa_connettore import MappaConnettore

ISTAT = "058091"
LETTO_IL = "2026-08-22T09:00:00+00:00"
# Far-future age so freshness never depends on the wall clock in tests.
NEVER_STALE = 10**9

FLEET_PLATFORMS = (
    "municipium",
    "comweb",
    "peopleweb",
    "openweb",
    "openpa",
    "egov",
    "hgate",
)


def _mappa() -> MappaConnettore:
    return MappaConnettore(
        codice_istat=ISTAT,
        nome="Comune di Prova",
        sito="https://www.comune.prova.it",
        sondato_il=LETTO_IL,
    )


def _ufficio(nome: str, *, con_recapiti: bool) -> UfficioConnettore:
    return UfficioConnettore(
        nome=nome,
        url=f"https://www.comune.prova.it/uffici/{nome.lower()}",
        telefoni=["+39 06 000000"] if con_recapiti else [],
        email=[f"{nome.lower()}@comune.prova.it"] if con_recapiti else [],
        pec=[],
        orari=None,
        source_typed=con_recapiti,
        letto_il=LETTO_IL,
    )


def _esito(platform: str, *, popolato: bool = True) -> EsitoConnettore:
    if not popolato:
        return EsitoConnettore(codice_istat=ISTAT, piattaforma=platform, letto_il=LETTO_IL)
    return EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma=platform,
        letto_il=LETTO_IL,
        uffici=[
            _ufficio("Anagrafe", con_recapiti=True),
            _ufficio("Protocollo", con_recapiti=False),
        ],
        amministrazione_trasparente=AmministrazioneTrasparente(
            indice_url="https://www.comune.prova.it/at",
            bandi_attivi=[
                BandoAT(titolo="Bando A", url="https://www.comune.prova.it/at/a")
            ],
            pdf_presenti=True,
        ),
    )


def _request(capability: str, surface: Surface) -> DataRequest:
    return DataRequest(
        request_id=f"req-{capability}",
        source_id=ISTAT,
        surface=surface,
        capability=capability,
        freshness=FreshnessPolicy(max_age_seconds=NEVER_STALE),
        manifest_revision=0,
    )


# ── Registration & resolution order ─────────────────────────────────────────

@pytest.mark.parametrize(
    ("platform", "capability", "surface", "expected"),
    [
        ("municipium", "offices", Surface.ORDINARY_DATA, "municipium.base"),
        ("municipium", "transparency", Surface.TRANSPARENCY, "municipium.trasparenza"),
        ("comweb", "offices", Surface.ORDINARY_DATA, "comweb.base"),
        ("comweb", "transparency", Surface.TRANSPARENCY, "comweb.trasparenza"),
        ("peopleweb", "offices", Surface.ORDINARY_DATA, "peopleweb.base"),
        ("peopleweb", "transparency", Surface.TRANSPARENCY, "peopleweb.trasparenza"),
        ("openweb", "offices", Surface.ORDINARY_DATA, "openweb.base"),
        ("openweb", "transparency", Surface.TRANSPARENCY, "openweb.trasparenza"),
        ("openpa", "offices", Surface.ORDINARY_DATA, "openpa.base"),
        ("openpa", "transparency", Surface.TRANSPARENCY, "openpa.trasparenza"),
        ("egov", "offices", Surface.ORDINARY_DATA, "egov.base"),
        ("egov", "transparency", Surface.TRANSPARENCY, "egov.trasparenza"),
        ("hgate", "offices", Surface.ORDINARY_DATA, "hgate.base"),
        ("hgate", "transparency", Surface.TRANSPARENCY, "hgate.trasparenza"),
    ],
)
def test_fleet_unit_wins_for_its_platform_and_surface(platform, capability, surface, expected):
    registry = default_connector_registry()
    connector = registry.resolve(request=_request(capability, surface), platform_id=platform)
    assert connector is not None
    assert connector.name == expected


def test_fleet_does_not_claim_services_capability():
    # 'services' is BASE surface but no fleet unit serves it → the wildcard
    # scrape connector must win, never a fleet unit.
    registry = default_connector_registry()
    connector = registry.resolve(
        request=_request("services", Surface.ORDINARY_DATA), platform_id="municipium"
    )
    assert connector is not None
    fleet_names = {c.name for c in flotta_connectors()}
    assert connector.name not in fleet_names


def test_non_fleet_platform_does_not_resolve_to_a_fleet_unit():
    registry = default_connector_registry()
    connector = registry.resolve(
        request=_request("offices", Surface.ORDINARY_DATA), platform_id="urbi"
    )
    assert connector is not None
    fleet_names = {c.name for c in flotta_connectors()}
    assert connector.name not in fleet_names


def test_fleet_adapter_gates_each_platform_and_surface():
    adapters = default_adapter_registry()
    for platform in FLEET_PLATFORMS:
        assert adapters.resolve(
            platform_id=platform, surface=Surface.ORDINARY_DATA.value, capability="offices"
        ) is not None
        assert adapters.resolve(
            platform_id=platform, surface=Surface.TRANSPARENCY.value, capability="transparency"
        ) is not None


# ── Parity: v1 batch carries the v0 office rail content ──────────────────────

@pytest.mark.parametrize("platform", FLEET_PLATFORMS)
def test_offices_batch_mirrors_esito_uffici(platform):
    esito = _esito(platform)
    batch = CatalogRuntime().execute(
        _request("offices", Surface.ORDINARY_DATA),
        platform_id=platform,
        mappa=_mappa(),
        esito=esito,
    )
    assert batch is not None
    assert batch.access_mode is AccessMode.MEDIATED
    assert batch.status is DataStatus.FULFILLED
    assert list(batch.records) == [office.model_dump(mode="json") for office in esito.uffici]
    assert batch.connector.name == f"{platform}.base"
    assert batch.connector.version == "1.0.0"


@pytest.mark.parametrize("platform", FLEET_PLATFORMS)
def test_contacts_batch_only_offices_with_recapiti(platform):
    esito = _esito(platform)
    batch = CatalogRuntime().execute(
        _request("contacts", Surface.ORDINARY_DATA),
        platform_id=platform,
        mappa=_mappa(),
        esito=esito,
    )
    assert batch is not None
    assert batch.access_mode is AccessMode.MEDIATED
    assert [record["nome"] for record in batch.records] == ["Anagrafe"]
    assert batch.records[0]["telefoni"] == ["+39 06 000000"]


def _ufficio_arricchito() -> UfficioConnettore:
    """Ufficio con recapiti + i campi additivi Ramo 1 (indirizzo, responsabile)."""
    return UfficioConnettore(
        nome="Anagrafe",
        url="https://www.comune.prova.it/uffici/anagrafe",
        telefoni=["+39 06 000000"],
        email=["anagrafe@comune.prova.it"],
        pec=[],
        orari=None,
        source_typed=True,
        letto_il=LETTO_IL,
        indirizzo="Piazza del Comune 1",
        responsabile=Responsabile(nome="Mario Rossi", ruolo="Dirigente", email="rossi@comune.prova.it"),
    )


def test_offices_batch_carries_indirizzo_e_responsabile():
    """`offices` (dump completo) deve portare i campi additivi fino al batch —
    guardia contro un futuro passaggio da model_dump a un dict enumerato che
    li dimenticherebbe."""
    esito = EsitoConnettore(
        codice_istat=ISTAT, piattaforma="municipium", letto_il=LETTO_IL,
        uffici=[_ufficio_arricchito()],
    )
    batch = CatalogRuntime().execute(
        _request("offices", Surface.ORDINARY_DATA),
        platform_id="municipium", mappa=_mappa(), esito=esito,
    )
    assert batch is not None
    record = batch.records[0]
    assert record["indirizzo"] == "Piazza del Comune 1"
    assert record["responsabile"] == {
        "nome": "Mario Rossi", "ruolo": "Dirigente", "email": "rossi@comune.prova.it",
    }


def test_contacts_batch_include_indirizzo_non_responsabile():
    """`contacts` porta `indirizzo` (canale fisico) ma NON `responsabile`:
    l'accountability vive nella capability dedicata `responsible` (prossimo
    step), non nei recapiti."""
    esito = EsitoConnettore(
        codice_istat=ISTAT, piattaforma="municipium", letto_il=LETTO_IL,
        uffici=[_ufficio_arricchito()],
    )
    batch = CatalogRuntime().execute(
        _request("contacts", Surface.ORDINARY_DATA),
        platform_id="municipium", mappa=_mappa(), esito=esito,
    )
    assert batch is not None
    record = batch.records[0]
    assert record["indirizzo"] == "Piazza del Comune 1"
    assert "responsabile" not in record


def test_contacts_gate_invariato_indirizzo_supplementare():
    """L'indirizzo è supplementare: un ufficio col SOLO indirizzo (nessun
    recapito telematico) NON compare fra i contatti — gate invariato."""
    solo_indirizzo = UfficioConnettore(
        nome="Magazzino", url="https://www.comune.prova.it/uffici/magazzino",
        source_typed=False, letto_il=LETTO_IL, indirizzo="Via Depositi 9",
    )
    esito = EsitoConnettore(
        codice_istat=ISTAT, piattaforma="municipium", letto_il=LETTO_IL,
        uffici=[solo_indirizzo],
    )
    batch = CatalogRuntime().execute(
        _request("contacts", Surface.ORDINARY_DATA),
        platform_id="municipium", mappa=_mappa(), esito=esito,
    )
    assert batch is not None
    assert batch.records == ()
    assert batch.access_mode is AccessMode.UNAVAILABLE


@pytest.mark.parametrize("platform", FLEET_PLATFORMS)
def test_transparency_batch_mirrors_amministrazione_trasparente(platform):
    esito = _esito(platform)
    batch = CatalogRuntime().execute(
        _request("transparency", Surface.TRANSPARENCY),
        platform_id=platform,
        mappa=_mappa(),
        esito=esito,
    )
    assert batch is not None
    assert batch.access_mode is AccessMode.MEDIATED
    assert list(batch.records) == [esito.amministrazione_trasparente.model_dump(mode="json")]
    assert batch.connector.name == f"{platform}.trasparenza"


# ── Absent capability collapses to UNAVAILABLE / NOT_SUPPORTED ───────────────

@pytest.mark.parametrize("platform", FLEET_PLATFORMS)
def test_empty_esito_is_not_supported(platform):
    batch = CatalogRuntime().execute(
        _request("offices", Surface.ORDINARY_DATA),
        platform_id=platform,
        mappa=_mappa(),
        esito=_esito(platform, popolato=False),
    )
    assert batch is not None
    assert batch.access_mode is AccessMode.UNAVAILABLE
    assert batch.status is DataStatus.NOT_SUPPORTED
    assert batch.records == ()


def test_source_id_mismatch_is_rejected():
    connector = flotta_connectors()[0]  # municipium.base
    request = _request("offices", Surface.ORDINARY_DATA).model_copy(
        update={"source_id": "999999"}
    )
    with pytest.raises(ValueError):
        connector.retrieve(request, mappa=_mappa(), esito=_esito("municipium"))
