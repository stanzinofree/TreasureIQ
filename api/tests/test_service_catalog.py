"""Unit tests for the flat service-catalog reader (``service_catalog``).

Read-only lookup in ``{base}/{source_id}.json`` (schema
``{municipality_istat, services}``): a hit returns a validated
``ServiceReference``; a missing file/key or a malformed entry returns ``None`` so
the resolver falls back to the live connector.  The reader never writes and never
escapes ``base`` via a crafted ``source_id``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from treasureiq.catalog import service_catalog
from treasureiq.catalog.service_contracts import (
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
    ServiceReference,
)

_ISTAT = "058003"
_DISCOVERED = datetime(2026, 8, 26, tzinfo=timezone.utc)


def _reference(service_id: str = "058003:openpa:574") -> ServiceReference:
    return ServiceReference(
        service_id=service_id,
        title="Carta d'identità elettronica",
        source_url="https://comune.example.it/Servizi/CIE",
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION,
                url="https://comune.example.it/Servizi/CIE",
                source_url="https://comune.example.it/Servizi/CIE",
            ),
        ),
        provider_platform="openpa",
        discovered_at=_DISCOVERED,
    )


def _scrivi(base, istat: str, services: dict) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{istat}.json").write_text(
        json.dumps({"municipality_istat": istat, "services": services}, ensure_ascii=False),
        "utf-8",
    )


# 1 — hit: valid file + key → the validated ServiceReference
def test_hit_ritorna_reference(tmp_path):
    base = tmp_path / "catalog"
    ref = _reference()
    _scrivi(base, _ISTAT, {"carta_identita": ref.model_dump(mode="json")})
    got = service_catalog.carica(_ISTAT, ServiceKey.CARTA_IDENTITA, base=base)
    assert got == ref


# 2 — key absent in an otherwise valid file → None
def test_key_assente(tmp_path):
    base = tmp_path / "catalog"
    _scrivi(base, _ISTAT, {"cambio_residenza": _reference().model_dump(mode="json")})
    assert service_catalog.carica(_ISTAT, ServiceKey.CARTA_IDENTITA, base=base) is None


# 3 — file absent → None
def test_file_assente(tmp_path):
    base = tmp_path / "catalog"
    base.mkdir(parents=True)
    assert service_catalog.carica("099999", ServiceKey.CARTA_IDENTITA, base=base) is None


# 4 — malformed JSON → None (no raise)
def test_json_corrotto(tmp_path):
    base = tmp_path / "catalog"
    base.mkdir(parents=True)
    (base / f"{_ISTAT}.json").write_text("{ not json", "utf-8")
    assert service_catalog.carica(_ISTAT, ServiceKey.CARTA_IDENTITA, base=base) is None


# 5 — a malformed entry does NOT block a valid sibling key
def test_voce_malformata_non_blocca_sorella(tmp_path):
    base = tmp_path / "catalog"
    buona = _reference("058003:openpa:900")
    _scrivi(
        base,
        _ISTAT,
        {
            "carta_identita": {"title": "manca service_id/options"},  # invalida
            "cambio_residenza": buona.model_dump(mode="json"),
        },
    )
    assert service_catalog.carica(_ISTAT, ServiceKey.CARTA_IDENTITA, base=base) is None
    assert service_catalog.carica(_ISTAT, ServiceKey.CAMBIO_RESIDENZA, base=base) == buona


# 6 — services not a dict / top-level not a dict → None
def test_forma_inattesa(tmp_path):
    base = tmp_path / "catalog"
    base.mkdir(parents=True)
    (base / f"{_ISTAT}.json").write_text(json.dumps({"services": []}), "utf-8")
    assert service_catalog.carica(_ISTAT, ServiceKey.CARTA_IDENTITA, base=base) is None
    (base / "058004.json").write_text(json.dumps(["a", "b"]), "utf-8")
    assert service_catalog.carica("058004", ServiceKey.CARTA_IDENTITA, base=base) is None


# 7 — a crafted source_id cannot escape base (path-traversal guard) → None
def test_source_id_traversal_respinto(tmp_path):
    base = tmp_path / "catalog"
    base.mkdir(parents=True)
    for cattivo in ("../secret", "a/b", "..", "", "058003/../058003"):
        assert service_catalog.carica(cattivo, ServiceKey.CARTA_IDENTITA, base=base) is None


# 8 — read-only: a lookup writes nothing (no file created, dir listing unchanged)
def test_nessuna_scrittura(tmp_path):
    base = tmp_path / "catalog"
    _scrivi(base, _ISTAT, {"carta_identita": _reference().model_dump(mode="json")})
    prima = sorted(p.name for p in base.iterdir())
    service_catalog.carica(_ISTAT, ServiceKey.CARTA_IDENTITA, base=base)
    service_catalog.carica("099999", ServiceKey.CARTA_IDENTITA, base=base)  # miss
    dopo = sorted(p.name for p in base.iterdir())
    assert prima == dopo == [f"{_ISTAT}.json"]
