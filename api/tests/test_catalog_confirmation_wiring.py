"""Fase 2D-iii — aggancio EndpointState + aderenza al path confirmation.

`confirm_inventory` ora, oltre al check, persiste lo stato dell'endpoint (che
transisce dal precedente) e il verdetto di aderenza fuso. Tutto dietro la
guardia dry-run (invariante I4).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from treasureiq.catalog import confirmation as confirmation_mod
from treasureiq.catalog.checks import CheckStatus
from treasureiq.catalog.confirmation import confirm_inventory
from treasureiq.catalog.endpoint_state import EndpointState
from treasureiq.catalog.service_contracts import SourceInventory
from treasureiq.ingest.piattaforma import Piattaforma

_URBI_AT = '<a href="/portale/ur1UR033.sto?ente=x">Amministrazione Trasparente</a>'
_AT_URL = "https://trasparenza.comune.example.it/portale/"


def _stub_fetch(monkeypatch, *, html):
    def fake(url, **_kw):
        if html is None:
            return None
        return httpx.Headers({}), html.encode("utf-8"), url
    monkeypatch.setattr(confirmation_mod, "fetch_guardato", fake)


def _inventario(tmp_path, *, transparency_url=_AT_URL):
    inventory = SourceInventory(
        source_id="058003",
        base_url="https://comune.example.it/",
        transparency_url=transparency_url,
        transparency_platform=Piattaforma.URBI.value,
        updated_at=datetime.now(timezone.utc),
    )
    inventory_dir = tmp_path / "inventario"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    (inventory_dir / "058003.json").write_text(
        inventory.model_dump_json(), encoding="utf-8"
    )


def test_confirm_persiste_stato_e_aderenza(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, html=_URBI_AT)
    _inventario(tmp_path)

    confirm_inventory(live_dir=tmp_path, source_id="058003", timeout=1.0)

    stato_path = tmp_path / "stato" / "transparency" / "058003.json"
    aderenza_path = tmp_path / "aderenza" / "transparency" / "058003.json"
    assert stato_path.exists()
    assert aderenza_path.exists()

    stato = EndpointState.model_validate_json(stato_path.read_text(encoding="utf-8"))
    assert stato.status is CheckStatus.OK
    assert stato.ok_consecutivi == 1
    assert stato.entrypoint_url == _AT_URL

    aderenza = json.loads(aderenza_path.read_text(encoding="utf-8"))
    # connettore = motore/plugin; piattaforma = ciò che il riconoscimento ha visto.
    assert aderenza["piattaforma"] == Piattaforma.URBI.value
    assert aderenza["connettore"] == "entrypoint_confirmation"
    # La confirmation non misura la copertura: verdetto onesto None.
    assert aderenza["coverage_score"] is None
    assert aderenza["verdetto"] is None


def test_confirm_transisce_lo_stato_fra_due_giri(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, html=_URBI_AT)
    _inventario(tmp_path)

    confirm_inventory(live_dir=tmp_path, source_id="058003", timeout=1.0)
    confirm_inventory(live_dir=tmp_path, source_id="058003", timeout=1.0)

    stato_path = tmp_path / "stato" / "transparency" / "058003.json"
    stato = EndpointState.model_validate_json(stato_path.read_text(encoding="utf-8"))
    # Secondo giro, stesso esito OK: la memoria transisce, non riparte.
    assert stato.ok_consecutivi == 2
    # `da` resta il primo istante (stato invariato fra i due giri).
    assert stato.da <= stato.ultimo_controllo_il


def test_confirm_url_cambiato_reinizializza_stato(monkeypatch, tmp_path):
    # Primo giro su un URL AT, poi l'inventario cambia URL sullo stesso comune:
    # il file di stato al percorso `stato/transparency/058003.json` resta, ma è
    # di un ALTRO endpoint. Deve ripartire da zero, non transire i vecchi contatori.
    _stub_fetch(monkeypatch, html=_URBI_AT)
    _inventario(tmp_path, transparency_url=_AT_URL)
    confirm_inventory(live_dir=tmp_path, source_id="058003", timeout=1.0)
    confirm_inventory(live_dir=tmp_path, source_id="058003", timeout=1.0)

    stato_path = tmp_path / "stato" / "transparency" / "058003.json"
    stato = EndpointState.model_validate_json(stato_path.read_text(encoding="utf-8"))
    assert stato.ok_consecutivi == 2  # due giri sullo stesso URL

    nuovo_url = "https://trasparenza-nuovo.comune.example.it/portale/"
    _inventario(tmp_path, transparency_url=nuovo_url)
    confirm_inventory(live_dir=tmp_path, source_id="058003", timeout=1.0)

    stato = EndpointState.model_validate_json(stato_path.read_text(encoding="utf-8"))
    # Endpoint nuovo: stato ripartito, non un ok_consecutivi==3 dal vecchio.
    assert stato.entrypoint_url == nuovo_url
    assert stato.ok_consecutivi == 1


def test_dry_run_non_scrive_stato_ne_aderenza(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, html=_URBI_AT)
    _inventario(tmp_path)

    confirm_inventory(live_dir=tmp_path, source_id="058003", timeout=1.0, dry_run=True)

    assert not (tmp_path / "stato").exists()
    assert not (tmp_path / "aderenza").exists()
    assert not (tmp_path / "check").exists()
