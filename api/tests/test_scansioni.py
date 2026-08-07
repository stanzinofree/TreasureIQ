"""Store di scansione e aderenza AgID, senza rete: mappe finte, disco tmp."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from treasureiq.mappa_connettore import AssetRest, AssetServizi, MappaConnettore, _estrai_logo
from treasureiq.scansioni import (
    ScansioneComune,
    aderenza_agid,
    carica_scansione,
    connettore_tipo,
    scansione_stantia,
)
import treasureiq.scansioni as scansioni


def _mappa(
    *,
    servizi_esposto: bool = False,
    uffici_esposto: bool = False,
    trasparenza_via: str = "scrape",
    contatti_via: str = "scrape",
    sito: str | None = "www.comune.x.it",
) -> MappaConnettore:
    return MappaConnettore(
        codice_istat="000000",
        nome="Comune Finto",
        sito=sito,
        sondato_il=datetime.now(timezone.utc).isoformat(),
        servizi=AssetServizi(esposto=servizi_esposto),
        uffici=AssetRest(esposto=uffici_esposto),
        contatti_via=contatti_via,
        amministrazione_trasparente_via=trasparenza_via,
    )


def test_aderenza_4_su_4_cento_per_cento():
    mappa = _mappa(
        servizi_esposto=True,
        uffici_esposto=True,
        trasparenza_via="REST",
        contatti_via="REST",
    )
    aderenza = aderenza_agid(mappa)
    assert aderenza is not None
    assert (aderenza.percento, aderenza.esposte, aderenza.definite) == (100, 4, 4)
    assert {s.nome: s.via for s in aderenza.superfici} == {
        "servizi": "REST",
        "uffici": "REST",
        "trasparenza": "REST",
        "contatti": "REST",
    }


def test_aderenza_3_su_4_come_figline():
    mappa = _mappa(servizi_esposto=True, uffici_esposto=True, trasparenza_via="REST")
    aderenza = aderenza_agid(mappa)
    assert aderenza is not None
    assert (aderenza.percento, aderenza.esposte, aderenza.definite) == (75, 3, 4)


def test_aderenza_2_su_4_come_perugia():
    mappa = _mappa(servizi_esposto=True, uffici_esposto=True)
    aderenza = aderenza_agid(mappa)
    assert aderenza is not None
    assert (aderenza.percento, aderenza.esposte, aderenza.definite) == (50, 2, 4)


def test_aderenza_none_fuori_da_agid():
    mappa = _mappa(servizi_esposto=False, uffici_esposto=False)
    assert aderenza_agid(mappa) is None


def test_connettore_tipo_agid():
    assert connettore_tipo(_mappa(servizi_esposto=True)) == "agid"


def test_connettore_tipo_solo_html():
    assert connettore_tipo(_mappa(sito="www.comune.y.it")) == "solo-html"


def test_connettore_tipo_non_sondato():
    assert connettore_tipo(_mappa(sito=None)) == "non-sondato"


def test_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(scansioni, "LIVE_DIR", tmp_path)
    mappa = _mappa(servizi_esposto=True, uffici_esposto=True, trasparenza_via="REST")
    record = ScansioneComune(
        codice_istat="048052",
        scansionato_il=datetime.now(timezone.utc).isoformat(),
        mappa=mappa,
        aderenza=aderenza_agid(mappa),
    )
    scansioni._in_cache(record)

    riletto = carica_scansione("048052")
    assert riletto is not None
    assert riletto.codice_istat == "048052"
    assert riletto.aderenza is not None
    assert riletto.aderenza.percento == 75


def test_carica_scansione_assente(tmp_path, monkeypatch):
    monkeypatch.setattr(scansioni, "LIVE_DIR", tmp_path)
    assert carica_scansione("999999") is None


def test_record_illeggibile_e_record_assente(tmp_path, monkeypatch):
    monkeypatch.setattr(scansioni, "LIVE_DIR", tmp_path)
    percorso = tmp_path / "scansioni" / "048052.json"
    percorso.parent.mkdir(parents=True)
    percorso.write_text("{non e' json valido", "utf-8")

    assert carica_scansione("048052") is None


@pytest.mark.parametrize(
    ("eta", "atteso"),
    [
        (timedelta(days=0), False),
        (timedelta(days=5), False),
        (timedelta(days=5, hours=23), False),
        (timedelta(days=6, seconds=1), True),
        (timedelta(days=7), True),
        (timedelta(days=30), True),
    ],
)
def test_scansione_stantia_a_cavallo_dei_6_giorni(eta, atteso):
    vecchio = datetime.now(timezone.utc) - eta
    record = ScansioneComune(
        codice_istat="048052",
        scansionato_il=vecchio.isoformat(),
        mappa=_mappa(),
    )
    assert scansione_stantia(record) is atteso


def test_scansione_stantia_timestamp_illeggibile_e_stantia():
    record = ScansioneComune(codice_istat="048052", scansionato_il="non-una-data", mappa=_mappa())
    assert scansione_stantia(record) is True


def test_logo_scartato_su_host_estraneo():
    pagina = '<link rel="icon" href="https://cdn-terzo.example/favicon.ico">'
    assert _estrai_logo(pagina, "https://www.comune.x.it") is None


def test_logo_accettato_su_stesso_host():
    pagina = '<link rel="icon" href="/wp-content/uploads/logo.png">'
    assert _estrai_logo(pagina, "https://www.comune.x.it") == (
        "https://www.comune.x.it/wp-content/uploads/logo.png"
    )
