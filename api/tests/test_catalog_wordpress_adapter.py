from datetime import datetime, timezone

from treasureiq.catalog import (
    AccessMode,
    DataRequest,
    FreshnessPolicy,
    RequestLimits,
    Surface,
    WordPressAgidAdapter,
)
from treasureiq.chat import respond
from treasureiq.connettore import EsitoConnettore, UfficioConnettore
from treasureiq.mappa_connettore import AssetRest, MappaConnettore


def _mappa(*, contatti_via: str = "scrape") -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito="https://comune.example",
        sondato_il=datetime.now(timezone.utc).isoformat(),
        uffici=AssetRest(esposto=True, rest_base="uffici"),
        contatti_via=contatti_via,
    )


def _esito() -> EsitoConnettore:
    return EsitoConnettore(
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


def _request(surface: Surface, capability: str) -> DataRequest:
    return DataRequest(
        request_id="req-1",
        source_id="058003",
        surface=surface,
        capability=capability,
        freshness=FreshnessPolicy(max_age_seconds=3600),
        limits=RequestLimits(max_records=10),
        manifest_revision=1,
    )


def test_wordpress_adapter_marks_scraped_contacts_as_mediated() -> None:
    batch = WordPressAgidAdapter().read(_request(Surface.ORDINARY_DATA, "contacts"), mappa=_mappa(), esito=_esito())

    assert batch.access_mode is AccessMode.MEDIATED
    assert batch.records[0]["telefoni"] == ["060000000"]
    assert batch.connector.name == "wordpress_agid"


def test_wordpress_adapter_marks_direct_offices_and_uses_evidence() -> None:
    batch = WordPressAgidAdapter().read(_request(Surface.ORDINARY_DATA, "offices"), mappa=_mappa(), esito=_esito())

    assert batch.access_mode is AccessMode.DIRECT
    assert batch.status.value == "fulfilled"
    assert batch.evidence[0].evidence_id == "https://comune.example/anagrafe"


def test_wordpress_adapter_reports_unavailable_capability_without_data() -> None:
    mappa = _mappa()
    mappa.uffici.esposto = False
    batch = WordPressAgidAdapter().read(_request(Surface.ORDINARY_DATA, "offices"), mappa=mappa, esito=None)

    assert batch.access_mode is AccessMode.UNAVAILABLE
    assert batch.status.value == "not_supported"


def test_chat_projection_emits_one_batch_per_catalog_capability(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "treasureiq.mappa_connettore._da_cache",
        lambda _istat: _mappa(),
    )

    batches = respond._data_batches_da_connettore(_esito())

    assert [(batch.surface, batch.capability) for batch in batches] == [
        (Surface.ORDINARY_DATA, "services"),
        (Surface.ORDINARY_DATA, "offices"),
        (Surface.ORDINARY_DATA, "contacts"),
        (Surface.TRANSPARENCY, "transparency"),
    ]
    assert batches[2].access_mode is AccessMode.MEDIATED

    plan, selected = respond._plan_connettore(_esito(), batches)
    assert plan is not None
    assert plan.steps[0].capability == "offices"
    assert selected is not None
    assert selected.capability == "offices"


def test_chat_projection_skips_unregistered_platform(monkeypatch) -> None:
    monkeypatch.setattr(
        "treasureiq.mappa_connettore._da_cache",
        lambda _istat: _mappa(),
    )
    esito = _esito().model_copy(update={"piattaforma": "halley"})

    assert respond._data_batches_da_connettore(esito) == []
