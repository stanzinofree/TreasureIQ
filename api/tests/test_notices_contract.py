"""Golden tests for the canonical `notices` contract (Ramo 2, slice 1).

Cover the pure pipeline `BandiLiveEsito (neutro) -> NoticeSnapshot -> DataBatch`:
presentation fields are dropped, coverage drives access_mode/status per the
Ramo 2 table, and D-07 honesty holds (deadline only when verified).
"""

from __future__ import annotations

from datetime import datetime, timezone

from treasureiq.bandi_live import BandiLiveEsito, BandoArricchito, Documento
from treasureiq.catalog.contracts import AccessMode, CAPABILITY_NOTICES
from treasureiq.catalog.data_contracts import (
    DataRequest,
    DataStatus,
    FreshnessPolicy,
    Surface,
)
from treasureiq.catalog.notices import (
    NoticeSnapshot,
    notices_batch,
    snapshot_da_bandi_live,
)
from treasureiq.schema import Opportunity, Source

_ISTAT = "058003"
_NOW = datetime.now(timezone.utc).isoformat()


def _source(*, connector: str = "bandi_live_cpt") -> Source:
    return Source(
        ente="Comune di Albano Laziale",
        connector=connector,
        url="https://www.comune.albanolaziale.rm.it/bando/1",
        fetched_at=datetime(2026, 8, 23, 6, 0, tzinfo=timezone.utc),
        raw_hash="deadbeef",
    )


def _bando(
    *,
    id_: str = "op-1",
    title: str = "Contributo affitto 2026",
    scadenza: str | None = None,
    scadenza_verificata: bool = False,
    tipo: str | None = None,
    documenti: list[Documento] | None = None,
    consigliato: bool = False,
    corrisponde: bool | None = None,
) -> BandoArricchito:
    opp = Opportunity.model_construct(id=id_, title=title, source=_source())
    return BandoArricchito(
        opportunity=opp,
        scadenza=scadenza,
        scadenza_verificata=scadenza_verificata,
        tipo=tipo,
        documenti=documenti or [],
        # presentation fields — must NOT survive into the canonical record
        consigliato=consigliato,
        corrisponde=corrisponde,
    )


def _esito(*, esito: str, bandi=None, gradino="cpt") -> BandiLiveEsito:
    return BandiLiveEsito(
        codice_istat=_ISTAT,
        comune_nome="Albano Laziale",
        esito=esito,
        gradino=gradino,
        verificato_il=_NOW,
        bandi=bandi or [],
        tema="casa",  # presentation — must NOT survive
        piattaforma_at="wordpress_agid",
        connettore_at="wordpress_agid_at",  # connector name/id, NOT a URL
    )


def _request() -> DataRequest:
    return DataRequest(
        request_id="req-1",
        source_id=_ISTAT,
        surface=Surface.TRANSPARENCY,
        capability=CAPABILITY_NOTICES,
        manifest_revision=1,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
    )


# --- snapshot: presentation fields are dropped --------------------------------


def test_snapshot_drops_presentation_fields():
    esito = _esito(
        esito="coperto_con_bandi",
        bandi=[_bando(consigliato=True, corrisponde=True)],
    )
    snap = snapshot_da_bandi_live(esito)

    assert isinstance(snap, NoticeSnapshot)
    assert snap.source_id == _ISTAT
    assert snap.coverage_status == "coperto_con_bandi"
    assert snap.retrieval_stage == "cpt"
    assert snap.platform_id == "wordpress_agid"
    # connettore_at is a connector name, not a URL: never leaked into source_url
    assert snap.source_url is None
    assert snap.connector_at == "wordpress_agid_at"
    # tema / consigliato / corrisponde have no home in the canonical model
    dumped = snap.model_dump()
    assert "tema" not in dumped
    record = snap.notices[0]
    assert "consigliato" not in record.model_dump()
    assert "corrisponde" not in record.model_dump()


# --- D-07: deadline only when verified ----------------------------------------


def test_deadline_present_only_when_verified():
    esito = _esito(
        esito="coperto_con_bandi",
        bandi=[
            _bando(id_="v", scadenza="31 dicembre 2026", scadenza_verificata=True),
            _bando(id_="nv", scadenza="forse a fine anno", scadenza_verificata=False),
        ],
    )
    snap = snapshot_da_bandi_live(esito)
    verified = next(n for n in snap.notices if n.notice_id == "v")
    unverified = next(n for n in snap.notices if n.notice_id == "nv")

    assert verified.deadline == "31 dicembre 2026"
    assert verified.deadline_verified is True
    # unverifiable page text is not quoted as a deadline
    assert unverified.deadline is None
    assert unverified.deadline_verified is False


# --- documents carried verbatim -----------------------------------------------


def test_documents_carried_verbatim():
    docs = [Documento(url="https://x/bando.pdf", etichetta="Bando integrale")]
    snap = snapshot_da_bandi_live(
        _esito(esito="coperto_con_bandi", bandi=[_bando(documenti=docs)])
    )
    got = snap.notices[0].documents
    assert len(got) == 1
    assert got[0].url == "https://x/bando.pdf"
    assert got[0].etichetta == "Bando integrale"


# --- DataBatch: coverage -> access_mode/status --------------------------------


def test_batch_coperto_con_bandi_is_mediated_fulfilled():
    snap = snapshot_da_bandi_live(
        _esito(esito="coperto_con_bandi", bandi=[_bando()])
    )
    batch = notices_batch(snap, _request())

    assert batch.access_mode is AccessMode.MEDIATED
    assert batch.status is DataStatus.FULFILLED
    assert batch.capability == CAPABILITY_NOTICES
    assert batch.surface is Surface.TRANSPARENCY
    assert batch.source_id == _ISTAT
    assert len(batch.records) == 1
    assert batch.connector.name == "bandi_live"


def test_batch_coperto_senza_bandi_is_mediated_empty():
    # Codex correction: source read and empty != source unreadable.
    snap = snapshot_da_bandi_live(_esito(esito="coperto_senza_bandi", bandi=[]))
    batch = notices_batch(snap, _request())

    assert batch.access_mode is AccessMode.MEDIATED
    assert batch.status is DataStatus.EMPTY
    assert batch.records == ()


def test_batch_non_coperto_is_unavailable_not_supported():
    snap = snapshot_da_bandi_live(_esito(esito="non_coperto", bandi=[], gradino=None))
    batch = notices_batch(snap, _request())

    assert batch.access_mode is AccessMode.UNAVAILABLE
    assert batch.status is DataStatus.NOT_SUPPORTED


def test_batch_comune_ignoto_is_unavailable_not_supported():
    snap = snapshot_da_bandi_live(_esito(esito="comune_ignoto", bandi=[], gradino=None))
    batch = notices_batch(snap, _request())

    assert batch.access_mode is AccessMode.UNAVAILABLE
    assert batch.status is DataStatus.NOT_SUPPORTED


# --- evidence + record shape --------------------------------------------------


def test_batch_evidence_points_at_record_urls():
    snap = snapshot_da_bandi_live(
        _esito(esito="coperto_con_bandi", bandi=[_bando()])
    )
    batch = notices_batch(snap, _request())

    assert len(batch.evidence) == 1
    assert batch.evidence[0].field == "url"
    assert batch.evidence[0].evidence_id == batch.records[0]["url"]
    # canonical record carries no presentation keys
    assert set(batch.records[0]) >= {"notice_id", "title", "url", "deadline_verified"}
    assert "consigliato" not in batch.records[0]
    assert "tema" not in batch.records[0]


# --- guard: request/snapshot must agree on the comune -------------------------


def test_batch_rejects_source_id_mismatch():
    snap = snapshot_da_bandi_live(_esito(esito="coperto_con_bandi", bandi=[_bando()]))
    bad = DataRequest(
        request_id="req-x",
        source_id="099999",
        surface=Surface.TRANSPARENCY,
        capability=CAPABILITY_NOTICES,
        manifest_revision=1,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
    )
    try:
        notices_batch(snap, bad)
        raise AssertionError("expected ValueError on source_id mismatch")
    except ValueError:
        pass


def test_batch_rejects_wrong_surface():
    snap = snapshot_da_bandi_live(_esito(esito="coperto_con_bandi", bandi=[_bando()]))
    bad = DataRequest(
        request_id="req-s",
        source_id=_ISTAT,
        surface=Surface.SERVICE_PORTAL,
        capability=CAPABILITY_NOTICES,
        manifest_revision=1,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
    )
    try:
        notices_batch(snap, bad)
        raise AssertionError("expected ValueError on non-TRANSPARENCY surface")
    except ValueError:
        pass


def test_batch_rejects_wrong_capability():
    snap = snapshot_da_bandi_live(_esito(esito="coperto_con_bandi", bandi=[_bando()]))
    bad = DataRequest(
        request_id="req-c",
        source_id=_ISTAT,
        surface=Surface.TRANSPARENCY,
        capability="offices",
        manifest_revision=1,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
    )
    try:
        notices_batch(snap, bad)
        raise AssertionError("expected ValueError on wrong capability")
    except ValueError:
        pass
