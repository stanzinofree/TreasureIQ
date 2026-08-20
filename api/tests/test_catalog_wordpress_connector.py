from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessMode,
    DataRequest,
    DataStatus,
    FreshnessPolicy,
    Surface,
    WordPressAgidConnector,
)
from treasureiq.connettore import EsitoConnettore, UfficioConnettore
from treasureiq.mappa_connettore import AssetRest, MappaConnettore


def _mappa() -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito="https://comune.example",
        sondato_il=datetime.now(timezone.utc).isoformat(),
        uffici=AssetRest(esposto=True, rest_base="uffici"),
    )


def _request(capability: str) -> DataRequest:
    return DataRequest(
        request_id=f"req-{capability}",
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        capability=capability,
        freshness=FreshnessPolicy(max_age_seconds=3600),
        manifest_revision=1,
    )


def test_wordpress_connector_projects_measured_offices() -> None:
    esito = EsitoConnettore(
        codice_istat="058003",
        piattaforma="wordpress_agid",
        letto_il=datetime.now(timezone.utc).isoformat(),
        uffici=[
            UfficioConnettore(
                nome="Anagrafe",
                url="https://comune.example/anagrafe",
                telefoni=["060000000"],
                source_typed=False,
                letto_il=datetime.now(timezone.utc).isoformat(),
            )
        ],
    )

    result = WordPressAgidConnector().retrieve(_request("offices"), mappa=_mappa(), esito=esito)

    assert result.status is DataStatus.FULFILLED
    assert result.access_mode is AccessMode.DIRECT
    assert result.records[0]["nome"] == "Anagrafe"
    assert result.connector.name == "wordpress_agid"


def test_wordpress_connector_does_not_invent_unavailable_data() -> None:
    mappa = _mappa()
    mappa.uffici.esposto = False

    result = WordPressAgidConnector().retrieve(_request("offices"), mappa=mappa, esito=None)

    assert result.status is DataStatus.NOT_SUPPORTED
    assert result.access_mode is AccessMode.UNAVAILABLE
    assert result.records == ()
