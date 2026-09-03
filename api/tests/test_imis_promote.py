"""Entrypoint di promozione IMIS: gate, scrittura catalogo, rapporto, CLI.

Net-free: la raccolta live è dietro un seam (`Raccoglitore`); qui si inietta uno
stub che restituisce ServiceReference costruite a mano.  Copre i tre casi guida —
Vigolana (promuovibile on-contract), Imer (auth GISCO fuori allowlist), un GISCO
generico — più skip-esistente, dry-run, zero-overwrite e wiring della CLI.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from treasureiq.catalog import imis_promote, service_catalog
from treasureiq.catalog.imis_promote import Esito, esegui, main, valuta_referenza
from treasureiq.catalog.service_contracts import (
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
)
from treasureiq.catalog.service_contracts import ServiceReference

KEY = ServiceKey.TRIBUTI_IMU
PROMO = "2026-09-02T00:00:00Z"

_COMUNE_VIG = "https://www.comune.vigolana.tn.it/Servizi/IMIS-on-line"
_DGE_VIG = "https://dgegovpa.it/Vigolana/login"
_COMUNE_IMER = "https://www.comune.imer.tn.it/Servizi/Calcolatore-IMIS"
_GISCO_IMER = "https://imisimer.giscoservice.it/"


def _info(url: str) -> ServiceAccessOption:
    return ServiceAccessOption(mode=ServiceAccessMode.INFORMATION, url=url, source_url=url)


def _auth(url: str) -> ServiceAccessOption:
    return ServiceAccessOption(
        mode=ServiceAccessMode.AUTHENTICATED_ONLINE, url=url, requires_authentication=True
    )


def _ref(service_id: str, source_url: str, *options: ServiceAccessOption) -> ServiceReference:
    return ServiceReference(
        service_id=service_id,
        title="IMIS on line",
        source_url=source_url,
        options=tuple(options),
        discovered_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )


def _ref_vigolana() -> ServiceReference:
    return _ref("022236:openpa:1415", _COMUNE_VIG, _info(_COMUNE_VIG), _auth(_DGE_VIG))


def _ref_imer_gisco() -> ServiceReference:
    return _ref("022097:openpa:900", _COMUNE_IMER, _info(_COMUNE_IMER), _auth(_GISCO_IMER))


class _Stub:
    """Raccoglitore iniettabile: mappa istat→reference; conta le chiamate."""

    def __init__(self, mapping: dict[str, ServiceReference]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def __call__(self, istat: str, key: ServiceKey):
        self.calls.append(istat)
        ref = self.mapping.get(istat)
        return (ref, "ok") if ref is not None else (None, "assente")


# --- valuta_referenza (gate puro) ------------------------------------------ #
def test_vigolana_on_contract_promossa():
    v = valuta_referenza(_ref_vigolana(), "022236")
    assert v.esito is Esito.PROMOSSO
    assert v.delegated_host == "DGE"
    assert v.motivi == ()


def test_imer_auth_gisco_esclusa():
    v = valuta_referenza(_ref_imer_gisco(), "022097")
    assert v.esito is Esito.ESCLUSO
    assert v.motivi  # host GISCO fuori allowlist


def test_gisco_generico_escluso():
    ref = _ref(
        "022115:openpa:1",
        "https://www.comune.mezzano.tn.it/Servizi/Calcolatore-IMIS",
        _info("https://www.comune.mezzano.tn.it/Servizi/Calcolatore-IMIS"),
        _auth("https://imismezzano.giscoservice.it/"),
    )
    assert valuta_referenza(ref, "022115").esito is Esito.ESCLUSO


def test_vigolana_ref_ma_istat_diverso_esclusa():
    # Stessa reference DGE, ISTAT non ammesso per DGE: il gate rifiuta.
    v = valuta_referenza(_ref_vigolana(), "022097")
    assert v.esito is Esito.ESCLUSO
    assert any("022097" in m for m in v.motivi)


# --- esegui: scrittura, round-trip, confini -------------------------------- #
def test_apply_scrive_e_roundtrip(tmp_path: Path):
    base = tmp_path / "catalog"
    stub = _Stub({"022236": _ref_vigolana()})
    rap = esegui(["022236"], KEY, base=base, promo_date=PROMO, apply=True, raccogli=stub)

    assert [v.istat for v in rap.promossi] == ["022236"]
    assert not rap.esclusi and not rap.skip

    # Round-trip attraverso il reader ufficiale (unico contratto).
    letto = service_catalog.carica("022236", KEY, base=base)
    assert letto is not None
    assert letto.service_id == "022236:openpa:1415"
    assert any(o.mode is ServiceAccessMode.AUTHENTICATED_ONLINE for o in letto.options)

    testo = (base / "022236.json").read_text(encoding="utf-8")
    assert not testo.endswith("\n")  # formato byte-fedele, nessun newline finale
    doc = json.loads(testo)
    assert doc["municipality_istat"] == "022236"
    assert doc["services"][KEY.value]["discovered_at"] == PROMO


def test_apply_preserva_servizi_esistenti(tmp_path: Path):
    base = tmp_path / "catalog"
    base.mkdir(parents=True)
    esistente = {
        "municipality_istat": "022236",
        "services": {"carta_identita": {"segnaposto": True}},
    }
    (base / "022236.json").write_text(
        json.dumps(esistente, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    esegui(["022236"], KEY, base=base, promo_date=PROMO, apply=True, raccogli=_Stub({"022236": _ref_vigolana()}))
    doc = json.loads((base / "022236.json").read_text(encoding="utf-8"))
    assert "carta_identita" in doc["services"]  # non rimosso
    assert KEY.value in doc["services"]  # aggiunto


def test_dry_run_non_scrive(tmp_path: Path):
    base = tmp_path / "catalog"
    rap = esegui(["022236"], KEY, base=base, promo_date=PROMO, apply=False, raccogli=_Stub({"022236": _ref_vigolana()}))
    assert [v.istat for v in rap.promossi] == ["022236"]
    assert not (base / "022236.json").exists()  # dry-run: nessuna scrittura


def test_skip_esistente_non_raccoglie(tmp_path: Path):
    base = tmp_path / "catalog"
    base.mkdir(parents=True)
    doc = {"municipality_istat": "022236", "services": {KEY.value: {"gia": True}}}
    (base / "022236.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    stub = _Stub({"022236": _ref_vigolana()})
    rap = esegui(["022236"], KEY, base=base, promo_date=PROMO, apply=True, raccogli=stub)
    assert [v.istat for v in rap.skip] == ["022236"]
    assert stub.calls == []  # zero-overwrite: non raccoglie nemmeno
    # la voce preesistente non è stata toccata
    assert json.loads((base / "022236.json").read_text(encoding="utf-8"))["services"][KEY.value] == {"gia": True}


def test_esclusa_non_scrive(tmp_path: Path):
    base = tmp_path / "catalog"
    esegui(["022097"], KEY, base=base, promo_date=PROMO, apply=True, raccogli=_Stub({"022097": _ref_imer_gisco()}))
    assert not (base / "022097.json").exists()


def test_raccolta_fallita_escludi(tmp_path: Path):
    base = tmp_path / "catalog"
    rap = esegui(["022236"], KEY, base=base, promo_date=PROMO, apply=True, raccogli=_Stub({}))
    assert [v.istat for v in rap.esclusi] == ["022236"]
    assert any("raccolta" in m for m in rap.esclusi[0].motivi)


def test_rapporto_as_dict_conta():
    rap = esegui(
        ["022236", "022097"],
        KEY,
        base=Path("/does-not-exist"),
        promo_date=PROMO,
        apply=False,
        raccogli=_Stub({"022236": _ref_vigolana(), "022097": _ref_imer_gisco()}),
    )
    d = rap.as_dict()
    assert d["totali"] == {"promossi": 1, "esclusi": 1, "skip_esistenti": 0}
    assert d["apply"] is False


# --- CLI (wiring) ----------------------------------------------------------- #
def test_main_apply_scrive(tmp_path: Path):
    stub = _Stub({"022236": _ref_vigolana()})
    rc = main(
        ["--istat", "022236", "--apply", "--data-dir", str(tmp_path), "--promo-date", PROMO],
        raccogli=stub,
    )
    assert rc == 0
    assert service_catalog.carica("022236", KEY, base=tmp_path / "catalog") is not None


def test_main_dry_run_default(tmp_path: Path):
    stub = _Stub({"022236": _ref_vigolana()})
    rc = main(["--istat", "022236", "--data-dir", str(tmp_path)], raccogli=stub)
    assert rc == 0
    assert not (tmp_path / "catalog" / "022236.json").exists()


def test_main_istat_file(tmp_path: Path):
    f = tmp_path / "lista.txt"
    f.write_text("022236\n# commento\n\n022097\n", encoding="utf-8")
    stub = _Stub({"022236": _ref_vigolana(), "022097": _ref_imer_gisco()})
    rc = main(["--istat-file", str(f), "--data-dir", str(tmp_path)], raccogli=stub)
    assert rc == 0
    assert stub.calls == ["022236", "022097"]  # letti in ordine, commenti/vuoti scartati


def test_live_default_non_importa_rete_a_modulo():
    # Il modulo è importabile senza toccare la rete: la raccolta live vive
    # dietro import ritardati, istanziati solo quando serve.
    assert hasattr(imis_promote, "RaccoglitoreLive")
