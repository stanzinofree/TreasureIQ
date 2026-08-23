"""Golden tests for the read-time SP merge (Ramo 3, Slice 6).

Pure, no network, no cache write.  Pin ``merge_service_portals``: per-link
evidence only (§2), URL normalisation + query disambiguation, mode/url
immutability, no invented auth, identity on absent/empty/mismatched inventory,
idempotence — and the review's three obligatory checks: the BASE reference in
cache is unchanged after the merge, the DataBatch carries the enriched reference
with the ``sp_*`` fields, and the cache file's mtime/bytes never change.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from treasureiq.catalog import service_cache
from treasureiq.catalog.contracts import ConnectorRef
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_batch import service_reference_batch
from treasureiq.catalog.service_contracts import (
    AuthenticationMethod,
    ResolvedService,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
    ServicePortalCandidate,
    ServicePortalGroup,
    ServicePortalRole,
    ServiceReference,
    SourceInventory,
)
from treasureiq.catalog.service_merge import merge_service_portals

_SOURCE = "058003"
_CONN = ConnectorRef(name="wordpress_agid_service", version="1")
_QUANDO = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
_SCOPERTA = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _auth_option(url: str, **kw) -> ServiceAccessOption:
    kw.setdefault("requires_authentication", True)
    return ServiceAccessOption(mode=ServiceAccessMode.AUTHENTICATED_ONLINE, url=url, **kw)


def _reference(*options: ServiceAccessOption, auth_url: str = "https://portale.x/cie") -> ServiceReference:
    opts = options or (
        ServiceAccessOption(mode=ServiceAccessMode.INFORMATION, url="https://comune.x/servizi/cie"),
        ServiceAccessOption(
            mode=ServiceAccessMode.DOWNLOAD,
            url="https://comune.x/servizi/cie/modulo.pdf",
        ),
        _auth_option(auth_url, authentication=(AuthenticationMethod.SPID,)),
    )
    return ServiceReference(
        service_id=f"{_SOURCE}:wp:42",
        title="Carta d'identità elettronica",
        source_url="https://comune.x/servizi/cie",
        options=opts,
        discovered_at=_SCOPERTA,
    )


def _candidate(url: str, **kw) -> ServicePortalCandidate:
    kw.setdefault("label", "Sportello telematico")
    kw.setdefault("source_url", "https://comune.x/servizi/cie")
    kw.setdefault("discovered_at", _SCOPERTA)
    return ServicePortalCandidate(url=url, **kw)


def _inventory(*candidates: ServicePortalCandidate, groups=(), source_id: str = _SOURCE) -> SourceInventory:
    return SourceInventory(
        source_id=source_id,
        base_url="https://comune.x",
        service_portals=candidates,
        service_portal_groups=groups,
        updated_at=_QUANDO,
    )


def _auth(ref: ServiceReference) -> ServiceAccessOption:
    return next(o for o in ref.options if o.mode is ServiceAccessMode.AUTHENTICATED_ONLINE)


# 1 — per-link association → enrichment; URL invariato.
def test_associazione_per_link_arricchisce():
    ref = _reference()
    inv = _inventory(
        _candidate(
            "https://portale.x/cie",
            role=ServicePortalRole.ONLINE_SERVICE,
            platform_id="egov",
            fingerprint="fp-1",
            provider_hint="Vendor X",
            authentication=(AuthenticationMethod.CIE,),
        )
    )
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    o = _auth(out)
    assert str(o.url) == "https://portale.x/cie"
    assert o.mode is ServiceAccessMode.AUTHENTICATED_ONLINE
    assert o.sp_platform_id == "egov"
    assert o.sp_role is ServicePortalRole.ONLINE_SERVICE
    assert o.sp_fingerprint == "fp-1"
    assert o.provider == "Vendor X"
    assert o.authentication == (AuthenticationMethod.SPID, AuthenticationMethod.CIE)


# 2 — URL match con normalizzazione (www/schema/trailing slash).
def test_url_normalizzato():
    ref = _reference(auth_url="https://portale.x/cie")
    inv = _inventory(_candidate("http://www.portale.x/cie/", platform_id="egov"))
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert _auth(out).sp_platform_id == "egov"


# 2bis — query string: (i) esatto, (ii) ambiguo → no match, (iii) uno solo.
def test_query_string_esatta():
    ref = _reference(auth_url="https://portale.x/serv?id=7")
    inv = _inventory(
        _candidate("https://portale.x/serv?id=7", platform_id="giusto"),
        _candidate("https://portale.x/serv?id=9", platform_id="sbagliato"),
    )
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert _auth(out).sp_platform_id == "giusto"


def test_query_base_con_candidato_senza_query_no_match():
    ref = _reference(auth_url="https://portale.x/serv?id=7")
    inv = _inventory(_candidate("https://portale.x/serv", platform_id="egov"))
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert _auth(out).sp_platform_id is None


def test_base_senza_query_due_candidati_ambiguo_no_match():
    ref = _reference(auth_url="https://portale.x/serv")
    inv = _inventory(
        _candidate("https://portale.x/serv?id=7", platform_id="a"),
        _candidate("https://portale.x/serv?id=9", platform_id="b"),
    )
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert _auth(out).sp_platform_id is None


def test_base_senza_query_un_candidato_match():
    ref = _reference(auth_url="https://portale.x/serv")
    inv = _inventory(_candidate("https://portale.x/serv?id=7", platform_id="egov"))
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert _auth(out).sp_platform_id == "egov"


# 3 — candidato SP non referenziato → ignorato, reference invariata.
def test_candidato_non_referenziato_ignorato():
    ref = _reference()
    inv = _inventory(_candidate("https://altro.x/area", platform_id="egov"))
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert out == ref
    assert len(out.options) == len(ref.options)


# 4 — PERSONAL_AREA senza link dalla pagina → mai associato (regola 3).
def test_portale_generico_non_automatico():
    ref = _reference()  # opzione auth verso portale.x/cie
    inv = _inventory(
        _candidate(
            "https://portale.x/areapersonale",
            role=ServicePortalRole.PERSONAL_AREA,
            platform_id="egov",
        )
    )
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert out == ref  # nessun aggancio: URL diverso, nessuna evidenza per-link.


# 4bis — Area personale linkata esplicitamente (D-S6-3).
def test_area_personale_linkata_esplicitamente():
    ref = _reference(
        ServiceAccessOption(mode=ServiceAccessMode.INFORMATION, url="https://comune.x/servizi/cie"),
        _auth_option(
            "https://portale.x/areapersonale",
            authentication=(AuthenticationMethod.SPID,),
        ),
    )
    inv = _inventory(
        _candidate(
            "https://portale.x/areapersonale",
            role=ServicePortalRole.PERSONAL_AREA,
            platform_id="egov",
        )
    )
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    o = _auth(out)
    assert o.sp_role is ServicePortalRole.PERSONAL_AREA
    assert o.mode is ServiceAccessMode.AUTHENTICATED_ONLINE  # mai DOWNLOAD
    assert o.authentication == (AuthenticationMethod.SPID,)  # invariata


# 5 — DOWNLOAD/INFORMATION intatte (regola 5, G1).
def test_download_information_intatte():
    ref = _reference()
    inv = _inventory(_candidate("https://portale.x/cie", platform_id="egov"))
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    for orig, nuovo in zip(ref.options, out.options):
        if orig.mode is not ServiceAccessMode.AUTHENTICATED_ONLINE:
            assert nuovo == orig
    # ordine preservato
    assert [o.mode for o in out.options] == [o.mode for o in ref.options]


# 6 — URL Base immutabile (G3).
def test_url_base_immutabile():
    ref = _reference(auth_url="https://portale.x/cie")
    inv = _inventory(_candidate("http://www.portale.x/cie/altro-url", platform_id="egov"))
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    # host+path diversi → no match; URL Base intatto comunque.
    assert str(_auth(out).url) == "https://portale.x/cie"


# 7 — nessun metodo di auth inventato (G4).
def test_nessun_metodo_inventato():
    ref = _reference(
        ServiceAccessOption(mode=ServiceAccessMode.INFORMATION, url="https://comune.x/servizi/cie"),
        _auth_option("https://portale.x/cie"),  # authentication vuota
    )
    inv = _inventory(_candidate("https://portale.x/cie", platform_id="egov"))  # auth vuota
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert _auth(out).authentication == ()


# 8 — identità su inventory assente/vuoto (G6), source_id diverso (G7), idempotenza.
def test_identita_inventory_assente():
    ref = _reference()
    assert merge_service_portals(source_id=_SOURCE, reference=ref, inventory=None) is ref


def test_identita_inventory_vuoto():
    ref = _reference()
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=_inventory())
    assert out is ref


def test_identita_source_id_diverso():
    ref = _reference()
    inv = _inventory(_candidate("https://portale.x/cie", platform_id="egov"), source_id="999999")
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    assert out is ref  # G7: mai merge incrociato.


def test_provenienza_esistente_non_cancellata_da_inventory_incompleto():
    # Reference già arricchita (platform+role+fingerprint), poi rimerge con un
    # candidato allo stesso URL ma con metadati incompleti: i campi esistenti
    # restano, solo i mancanti si riempiono (conservazione, §3).
    ref = _reference(
        ServiceAccessOption(mode=ServiceAccessMode.INFORMATION, url="https://comune.x/servizi/cie"),
        _auth_option(
            "https://portale.x/cie",
            authentication=(AuthenticationMethod.SPID,),
            sp_platform_id="egov",
            sp_role=ServicePortalRole.ONLINE_SERVICE,
            sp_fingerprint="fp-1",
        ),
    )
    inv = _inventory(
        _candidate(
            "https://portale.x/cie",
            platform_id=None,  # incompleto: non deve cancellare "egov"
            role=ServicePortalRole.UNKNOWN,  # presente ma role già valorizzato → resta
            fingerprint=None,  # incompleto: non deve cancellare "fp-1"
        )
    )
    out = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    o = _auth(out)
    assert o.sp_platform_id == "egov"
    assert o.sp_role is ServicePortalRole.ONLINE_SERVICE
    assert o.sp_fingerprint == "fp-1"


def test_idempotenza():
    ref = _reference()
    inv = _inventory(
        _candidate(
            "https://portale.x/cie",
            platform_id="egov",
            authentication=(AuthenticationMethod.CIE,),
        )
    )
    una = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    due = merge_service_portals(source_id=_SOURCE, reference=una, inventory=inv)
    assert due == una


# 9 — read-time, no write: mtime/bytes del file cache invariati (review check 3).
def test_read_time_nessuna_scrittura_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(service_cache, "LIVE_DIR", tmp_path)
    ref = _reference()
    service_cache.salva(_SOURCE, ServiceKey.CARTA_IDENTITA, ref, _CONN, retrieved_at=_QUANDO)
    percorso = service_cache._percorso(_SOURCE)
    prima_mtime = percorso.stat().st_mtime_ns
    prima_bytes = percorso.read_bytes()

    inv = _inventory(_candidate("https://portale.x/cie", platform_id="egov"))
    merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)

    assert percorso.stat().st_mtime_ns == prima_mtime
    assert percorso.read_bytes() == prima_bytes
    # La reference Base in cache resta Base-only (review check 1).
    voce = service_cache.carica(
        _SOURCE, ServiceKey.CARTA_IDENTITA, policy=_policy()
    )
    assert _auth(voce.reference).sp_platform_id is None


# review check 2 — il DataBatch usa la reference arricchita e contiene i campi sp_*.
def test_databatch_porta_reference_arricchita():
    ref = _reference()
    inv = _inventory(
        _candidate(
            "https://portale.x/cie",
            platform_id="egov",
            role=ServicePortalRole.ONLINE_SERVICE,
            fingerprint="fp-1",
        )
    )
    arricchita = merge_service_portals(source_id=_SOURCE, reference=ref, inventory=inv)
    resolved = ResolvedService(
        reference=arricchita, retrieved_at=_QUANDO, from_cache=False, connector=_CONN
    )
    request = service_request(source_id=_SOURCE, service_key=ServiceKey.CARTA_IDENTITA)
    batch = service_reference_batch(resolved, request)
    assert batch.service_references == (arricchita,)
    auth_rec = next(
        r for r in batch.records if r["mode"] == ServiceAccessMode.AUTHENTICATED_ONLINE.value
    )
    assert auth_rec["sp_platform_id"] == "egov"
    assert auth_rec["sp_role"] == ServicePortalRole.ONLINE_SERVICE.value
    assert auth_rec["sp_fingerprint"] == "fp-1"


def _policy():
    from treasureiq.catalog.data_contracts import FreshnessPolicy

    return FreshnessPolicy(max_age_seconds=86400)
