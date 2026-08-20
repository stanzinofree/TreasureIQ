from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessMode,
    CatalogRuntime,
    ConnectorRegistry,
    AdapterRegistry,
    DataRequest,
    FreshnessPolicy,
    Surface,
)
from treasureiq.connettore import EsitoConnettore, UfficioConnettore
from treasureiq.mappa_connettore import AssetRest, MappaConnettore


def _request() -> DataRequest:
    return DataRequest(
        request_id="req-runtime",
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        capability="offices",
        freshness=FreshnessPolicy(max_age_seconds=3600),
        manifest_revision=1,
    )


def _mappa() -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito="https://comune.example",
        sondato_il=datetime.now(timezone.utc).isoformat(),
        uffici=AssetRest(esposto=True, rest_base="uffici"),
    )


def test_runtime_executes_connector_then_adapter() -> None:
    esito = EsitoConnettore(
        codice_istat="058003",
        piattaforma="wordpress_agid",
        letto_il=datetime.now(timezone.utc).isoformat(),
        uffici=[
            UfficioConnettore(
                nome="Anagrafe",
                url="https://comune.example/anagrafe",
                source_typed=False,
                letto_il=datetime.now(timezone.utc).isoformat(),
            )
        ],
    )

    batch = CatalogRuntime().execute(
        _request(), platform_id="wordpress_agid", mappa=_mappa(), esito=esito
    )

    assert batch is not None
    assert batch.access_mode is AccessMode.DIRECT
    assert batch.records[0]["nome"] == "Anagrafe"


def test_runtime_rejects_source_without_native_or_fallback_adapter() -> None:
    assert CatalogRuntime(connectors=ConnectorRegistry(), adapters=AdapterRegistry()).execute(
        _request(), platform_id="unknown", mappa=_mappa(), esito=None
    ) is None
