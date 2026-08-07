"""GET /api/comune/{codice_istat}: la rotta serve il record di scansione già
in store, mai un ricalcolo al volo. Store monkeypatchato su tmp_path — nessun
probe live in questi test."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

import treasureiq.scansioni as scansioni
from treasureiq.api import app
from treasureiq.mappa_connettore import AssetRest, AssetServizi, CategoriaServizio, MappaConnettore
from treasureiq.scansioni import ScansioneComune, aderenza_agid
from treasureiq.sonda_live import ContattiUrp

client = TestClient(app)


def _mappa(
    *,
    servizi_esposto: bool = False,
    uffici_esposto: bool = False,
    trasparenza_via: str = "scrape",
    contatti_via: str = "scrape",
    sito: str | None = "www.comune.x.it",
) -> MappaConnettore:
    return MappaConnettore(
        codice_istat="048052",
        nome="Comune di Figline",
        sito=sito,
        sondato_il=datetime.now(timezone.utc).isoformat(),
        servizi=AssetServizi(
            esposto=servizi_esposto,
            totale=4 if servizi_esposto else 0,
            categorie=[CategoriaServizio(nome="Anagrafe", conteggio=4, id=7, slug="anagrafe")]
            if servizi_esposto
            else [],
        ),
        uffici=AssetRest(esposto=uffici_esposto, totale=2 if uffici_esposto else 0),
        contatti_via=contatti_via,
        amministrazione_trasparente_via=trasparenza_via,
    )


def _registra(codice_istat: str, mappa: MappaConnettore, *, con_contatti: bool = False) -> None:
    record = ScansioneComune(
        codice_istat=codice_istat,
        scansionato_il=datetime.now(timezone.utc).isoformat(),
        mappa=mappa,
        aderenza=aderenza_agid(mappa),
        contatti=(
            ContattiUrp(telefoni=["055 123456"], email=["urp@comune.x.it"], pec=["pec@comune.x.it"], fonte="https://www.comune.x.it/urp")
            if con_contatti
            else None
        ),
        logo_url="https://www.comune.x.it/logo.png",
    )
    scansioni._in_cache(record)


def test_scheda_comune_record_presente_75_per_cento_come_figline(tmp_path, monkeypatch):
    monkeypatch.setattr(scansioni, "LIVE_DIR", tmp_path)
    mappa = _mappa(servizi_esposto=True, uffici_esposto=True, trasparenza_via="REST")
    _registra("048052", mappa, con_contatti=True)

    risposta = client.get("/api/comune/048052")
    assert risposta.status_code == 200
    corpo = risposta.json()

    assert corpo["aderenza"]["percento"] == 75
    assert corpo["aderenza"]["esposte"] == 3
    assert corpo["aderenza"]["definite"] == 4
    assert len(corpo["aderenza"]["superfici"]) == 4
    assert all(s["via"] for s in corpo["aderenza"]["superfici"])
    assert corpo["connettore_tipo"] == "agid"
    assert corpo["scansionato_il"]
    assert corpo["contatti"]["fonte"]
    assert "pubblicato letto" not in risposta.text


def test_scheda_comune_50_per_cento_come_perugia(tmp_path, monkeypatch):
    monkeypatch.setattr(scansioni, "LIVE_DIR", tmp_path)
    mappa = _mappa(servizi_esposto=True, uffici_esposto=True)
    _registra("054039", mappa)

    corpo = client.get("/api/comune/054039").json()
    assert corpo["aderenza"]["percento"] == 50
    assert corpo["aderenza"]["esposte"] == 2
    assert corpo["aderenza"]["definite"] == 4


def test_scheda_comune_non_agid_aderenza_null(tmp_path, monkeypatch):
    monkeypatch.setattr(scansioni, "LIVE_DIR", tmp_path)
    mappa = _mappa(servizi_esposto=False, uffici_esposto=False, sito="www.comune.y.it")
    _registra("999998", mappa)

    corpo = client.get("/api/comune/999998").json()
    assert corpo["aderenza"] is None
    assert corpo["connettore_tipo"] == "solo-html"


def test_scheda_comune_ignoto_404(tmp_path, monkeypatch):
    monkeypatch.setattr(scansioni, "LIVE_DIR", tmp_path)
    risposta = client.get("/api/comune/000000")
    assert risposta.status_code == 404
