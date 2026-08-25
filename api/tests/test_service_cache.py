"""Golden tests for the resolved-service cache (Ramo 3, Slice 2 + Slice 5 v2).

Pure unit tests: ``LIVE_DIR`` is redirected to ``tmp_path``, no network. They
pin the store contract — fresh round-trip, miss on absent/stale/version-mismatch/
corrupt, per-key isolation, atomic write, path-safety, timezone normalisation —
and the Slice 5 v2 additions: ``carica`` returns the whole ``CachedService``
(reference **and** provenance) and ``salva`` persists the ``connector``, so a v1
entry (schema-mismatch) is a miss and a v2 hit reports the stored connector.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from treasureiq.catalog import service_cache
from treasureiq.catalog.contracts import ConnectorRef
from treasureiq.catalog.data_contracts import FreshnessPolicy
from treasureiq.catalog.service_contracts import (
    SERVICE_CACHE_SCHEMA_VERSION,
    AuthenticationMethod,
    CachedService,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceCacheFile,
    ServiceKey,
    ServiceReference,
)

_POLICY = FreshnessPolicy(max_age_seconds=86400)
_CONN = ConnectorRef(name="wordpress_agid_service", version="1")


@pytest.fixture(autouse=True)
def _live_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(service_cache, "LIVE_DIR", tmp_path)
    return tmp_path


def _reference(service_id: str = "svc-cie") -> ServiceReference:
    """A reference with mixed access options (INFORMATION + DOWNLOAD + AUTH)."""
    return ServiceReference(
        service_id=service_id,
        title="Carta d'identità elettronica",
        source_url="https://comune.example.it/servizi/cie",
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION,
                url="https://comune.example.it/servizi/cie",
            ),
            ServiceAccessOption(
                mode=ServiceAccessMode.DOWNLOAD,
                url="https://comune.example.it/servizi/cie/modulo.pdf",
            ),
            ServiceAccessOption(
                mode=ServiceAccessMode.AUTHENTICATED_ONLINE,
                url="https://portale.example.it/cie",
                authentication=(AuthenticationMethod.SPID,),
                requires_authentication=True,
            ),
        ),
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _scrivi_raw(tmp_path, source_id: str, voci: tuple[CachedService, ...]) -> None:
    """Write a cache file directly (bypassing ``salva``) for guard-path tests."""
    percorso = tmp_path / "servizi-risolti" / f"{source_id}.json"
    percorso.parent.mkdir(parents=True, exist_ok=True)
    contenuto = ServiceCacheFile(
        source_id=source_id,
        entries=voci,
        updated_at=datetime.now(timezone.utc),
    )
    percorso.write_text(contenuto.model_dump_json(), "utf-8")


# 1 — salva then fresh carica returns the whole CachedService (reference + connector)
def test_salva_poi_carica_fresco():
    ref = _reference()
    service_cache.salva("058003", ServiceKey.CARTA_IDENTITA, ref, _CONN)
    letto = service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY)
    assert letto is not None
    assert letto.reference == ref
    assert letto.connector == _CONN


# 2 — carica on absent source / absent key → None
def test_carica_fonte_o_chiave_assente():
    assert service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY) is None
    service_cache.salva("058003", ServiceKey.CARTA_IDENTITA, _reference(), _CONN)
    assert service_cache.carica("058003", ServiceKey.TRIBUTI_IMU, policy=_POLICY) is None


# 3 — entry older than max_age_seconds → None (stale → live)
def test_carica_stale(tmp_path):
    vecchia = CachedService(
        service_key=ServiceKey.CARTA_IDENTITA,
        reference=_reference(),
        retrieved_at=datetime.now(timezone.utc) - timedelta(days=2),
        connector=_CONN,
    )
    _scrivi_raw(tmp_path, "058003", (vecchia,))
    assert service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY) is None


# 4 — entry with an older schema_version (v1, no connector semantics) → None (re-read)
def test_carica_versione_vecchia(tmp_path):
    voce = CachedService(
        service_key=ServiceKey.CARTA_IDENTITA,
        reference=_reference(),
        retrieved_at=datetime.now(timezone.utc),
        connector=_CONN,
        schema_version=SERVICE_CACHE_SCHEMA_VERSION - 1,
    )
    _scrivi_raw(tmp_path, "058003", (voce,))
    assert service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY) is None


# 4b — entry with a FUTURE schema_version → None (not safely readable)
def test_carica_versione_futura(tmp_path):
    voce = CachedService(
        service_key=ServiceKey.CARTA_IDENTITA,
        reference=_reference(),
        retrieved_at=datetime.now(timezone.utc),
        connector=_CONN,
        schema_version=SERVICE_CACHE_SCHEMA_VERSION + 1,
    )
    _scrivi_raw(tmp_path, "058003", (voce,))
    assert service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY) is None


# 4c (Slice 5, D-S5-7) — a fresh v2 entry is a hit and reports the stored connector
def test_carica_v2_riporta_connector(tmp_path):
    altro = ConnectorRef(name="municipium_service", version="3")
    voce = CachedService(
        service_key=ServiceKey.CARTA_IDENTITA,
        reference=_reference(),
        retrieved_at=datetime.now(timezone.utc),
        connector=altro,
    )
    _scrivi_raw(tmp_path, "058003", (voce,))
    letto = service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY)
    assert letto is not None and letto.connector == altro


# 5 — corrupt file → None, no crash
def test_carica_file_corrotto(tmp_path):
    percorso = tmp_path / "servizi-risolti" / "058003.json"
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text("{ not json", "utf-8")
    assert service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY) is None


# 5b — file whose internal source_id disagrees with the filename → miss
def test_carica_source_id_incoerente(tmp_path):
    voce = CachedService(
        service_key=ServiceKey.CARTA_IDENTITA,
        reference=_reference(),
        retrieved_at=datetime.now(timezone.utc),
        connector=_CONN,
    )
    # File 058003.json ma source_id interno = 058091 (rinominato/copiato a mano).
    percorso = tmp_path / "servizi-risolti" / "058003.json"
    percorso.parent.mkdir(parents=True, exist_ok=True)
    contenuto = ServiceCacheFile(
        source_id="058091",
        entries=(voce,),
        updated_at=datetime.now(timezone.utc),
    )
    percorso.write_text(contenuto.model_dump_json(), "utf-8")
    assert service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY) is None


# 6 — a second service_key does not clobber the first
def test_no_clobber_altre_chiavi():
    ref_cie = _reference("svc-cie")
    ref_tributi = _reference("svc-tributi")
    service_cache.salva("058003", ServiceKey.CARTA_IDENTITA, ref_cie, _CONN)
    service_cache.salva("058003", ServiceKey.TRIBUTI_IMU, ref_tributi, _CONN)
    cie = service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY)
    tributi = service_cache.carica("058003", ServiceKey.TRIBUTI_IMU, policy=_POLICY)
    assert cie is not None and cie.reference == ref_cie
    assert tributi is not None and tributi.reference == ref_tributi


# 6b — re-salva of the same key overwrites only that key
def test_re_salva_stessa_chiave():
    service_cache.salva("058003", ServiceKey.CARTA_IDENTITA, _reference("v1"), _CONN)
    service_cache.salva("058003", ServiceKey.CARTA_IDENTITA, _reference("v2"), _CONN)
    letto = service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY)
    assert letto is not None and letto.reference.service_id == "v2"


# 7 — same service_key, two source_id → isolated entries
def test_isolamento_per_fonte():
    service_cache.salva("058003", ServiceKey.CARTA_IDENTITA, _reference("albano"), _CONN)
    service_cache.salva("058091", ServiceKey.CARTA_IDENTITA, _reference("marino"), _CONN)
    a = service_cache.carica("058003", ServiceKey.CARTA_IDENTITA, policy=_POLICY)
    b = service_cache.carica("058091", ServiceKey.CARTA_IDENTITA, policy=_POLICY)
    assert a is not None and a.reference.service_id == "albano"
    assert b is not None and b.reference.service_id == "marino"


# 8 — unwritable mount → salva warns, no exception
def test_salva_mount_non_scrivibile(monkeypatch, tmp_path):
    blocco = tmp_path / "blocco"
    blocco.write_text("non una directory", "utf-8")  # a file where a dir is expected
    monkeypatch.setattr(service_cache, "LIVE_DIR", blocco / "sotto")
    service_cache.salva("058003", ServiceKey.CARTA_IDENTITA, _reference(), _CONN)  # must not raise


# 9 — no residual .tmp after salva (atomic write completed)
def test_nessun_tmp_residuo(tmp_path):
    service_cache.salva("058003", ServiceKey.CARTA_IDENTITA, _reference(), _CONN)
    residui = list((tmp_path / "servizi-risolti").glob("*.tmp"))
    assert residui == []


# 10 — invalid source_id / path traversal → rejected (raise)
@pytest.mark.parametrize("cattivo", ["../058003", "058/003", "..", "a\\b", "", "058 003"])
def test_source_id_non_valido_rifiutato(cattivo):
    with pytest.raises(ValueError):
        service_cache.carica(cattivo, ServiceKey.CARTA_IDENTITA, policy=_POLICY)
    with pytest.raises(ValueError):
        service_cache.salva(cattivo, ServiceKey.CARTA_IDENTITA, _reference(), _CONN)


# 11 — naive and aware timestamps normalise the same (both fresh)
def test_timestamp_naive_e_aware_normalizzati(tmp_path):
    aware = datetime.now(timezone.utc)
    naive = aware.replace(tzinfo=None)  # naive UTC, assumed UTC by the policy
    for source_id, quando in (("aware", aware), ("naive", naive)):
        voce = CachedService(
            service_key=ServiceKey.CARTA_IDENTITA,
            reference=_reference(source_id),
            retrieved_at=quando,
            connector=_CONN,
        )
        _scrivi_raw(tmp_path, source_id, (voce,))
        letto = service_cache.carica(source_id, ServiceKey.CARTA_IDENTITA, policy=_POLICY)
        assert letto is not None, f"{source_id} dovrebbe essere fresco"
