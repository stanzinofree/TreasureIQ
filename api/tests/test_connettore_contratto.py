"""Test di `connettore.py` (ciclo 10, brief B1): niente rete — store e
dispatcher isolati via monkeypatch, stesso stampo di `test_alberatura.py`/
`test_scansioni.py`."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import treasureiq.connettore as connettore_mod
from treasureiq.connettore import (
    AmministrazioneTrasparente,
    AreaAmministrativa,
    EsitoConnettore,
    UfficioConnettore,
    _da_store,
    _esito_vuoto,
    _in_store,
    leggi_connettore,
)
from treasureiq.ingest.piattaforma import Firma, Piattaforma
from treasureiq.sonda_live import ComuneNoto

ISTAT = "048052"


def _comune() -> ComuneNoto:
    return ComuneNoto(
        codice_istat=ISTAT, nome="Figline", provincia="FI", regione="Toscana", sito="www.comunefiv.it"
    )


def _esito(*, uffici: list[UfficioConnettore] | None = None,
           at: AmministrazioneTrasparente | None = None,
           letto_il: str | None = None) -> EsitoConnettore:
    return EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma=Piattaforma.MUNICIPIUM.value,
        letto_il=letto_il or datetime.now(timezone.utc).isoformat(),
        uffici=uffici or [],
        amministrazione_trasparente=at,
    )


class _RispostaFinta:
    def __init__(self, headers: dict[str, str] | None = None, text: str = "") -> None:
        self.headers = headers or {}
        self.text = text


class _SondaFinta:
    """Doppio minimale di `_Sonda`: solo `risposta`, come context manager."""

    def __init__(self, *, timeout: float = 8.0) -> None:
        self.timeout = timeout

    def __enter__(self) -> "_SondaFinta":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def risposta(self, url: str) -> _RispostaFinta:
        return _RispostaFinta(headers={"server": "municipium"}, text="<html></html>")


# --- Store (D-10) -----------------------------------------------------


def test_store_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    assert _da_store(ISTAT) is None
    ufficio = UfficioConnettore(
        nome="URP", url="https://www.comunefiv.it/urp", telefoni=["055123456"],
        source_typed=True, letto_il=datetime.now(timezone.utc).isoformat(),
    )
    esito = _esito(uffici=[ufficio])
    _in_store(esito)
    riletto = _da_store(ISTAT)
    assert riletto is not None
    assert riletto.codice_istat == ISTAT
    assert riletto.uffici[0].nome == "URP"
    assert riletto.letto_il == esito.letto_il  # mai riscritto


def test_ttl_scaduto_ritorna_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    vecchio = (datetime.now(timezone.utc) - timedelta(hours=connettore_mod.TTL_ORE + 1)).isoformat()
    esito = _esito(at=AmministrazioneTrasparente(indice_url="https://x/at"), letto_il=vecchio)
    _in_store(esito)
    assert _da_store(ISTAT) is None


def test_file_corrotto_ritorna_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    percorso = tmp_path / "connettore" / f"{ISTAT}.json"
    percorso.parent.mkdir(parents=True)
    percorso.write_text("{non e' json valido", "utf-8")
    assert _da_store(ISTAT) is None


def test_esito_vuoto_non_persistito_dal_dispatcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Esito senza uffici né AT: il dispatcher lo ritorna ma non lo scrive
    mai su disco (L-5)."""
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaFinta)
    monkeypatch.setattr(
        connettore_mod, "firma_da_risposta",
        lambda *, headers, html: Firma(piattaforma=Piattaforma.MUNICIPIUM, prova="municipium"),
    )

    fake_mod = types.ModuleType("treasureiq.municipium")
    fake_mod.leggi_municipium = lambda comune, sonda: _esito()  # uffici=[], at=None
    monkeypatch.setitem(sys.modules, "treasureiq.municipium", fake_mod)

    esito = leggi_connettore(ISTAT, usa_cache=False)
    assert esito is not None
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None
    assert _da_store(ISTAT) is None
    assert not (tmp_path / "connettore" / f"{ISTAT}.json").exists()


def test_esito_con_sole_aree_non_e_vuoto() -> None:
    """Regressione: eGov produce `uffici=[]` e riempie solo
    `aree_amministrative`; un esito così NON è vuoto e va cachato, altrimenti
    verrebbe ri-scrapato live a ogni query."""
    esito = EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma=Piattaforma.EGOV.value,
        letto_il=datetime.now(timezone.utc).isoformat(),
        aree_amministrative=[AreaAmministrativa(nome="Istruzione", url="https://x/EGSCHTST45.HBL?ARG=1")],
    )
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None
    assert not _esito_vuoto(esito)


# --- Dispatcher (deferred piattaforme, degrado muto) -------------------


def test_dispatcher_municipium_non_importabile_ritorna_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`treasureiq.municipium` non esiste ancora (B2): nessun crash, `None`."""
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaFinta)
    monkeypatch.setattr(
        connettore_mod, "firma_da_risposta",
        lambda *, headers, html: Firma(piattaforma=Piattaforma.MUNICIPIUM, prova="municipium"),
    )
    monkeypatch.setitem(sys.modules, "treasureiq.municipium", None)  # forza ImportError

    assert leggi_connettore(ISTAT, usa_cache=False) is None


def test_dispatcher_piattaforma_non_municipium_ritorna_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaFinta)
    # DRUPAL: nessun connettore la legge (a differenza di WORDPRESS_GENERICO,
    # ora instradata su `wordpress_agid.leggi_wordpress_agid`, D-09).
    monkeypatch.setattr(
        connettore_mod, "firma_da_risposta",
        lambda *, headers, html: Firma(piattaforma=Piattaforma.DRUPAL, prova="drupal"),
    )

    assert leggi_connettore(ISTAT, usa_cache=False) is None


def test_dispatcher_comune_ignoto_ritorna_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: None)
    assert leggi_connettore("000000", usa_cache=False) is None
