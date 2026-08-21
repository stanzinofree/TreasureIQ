"""Test di `connettore.py` (ciclo 10, brief B1): niente rete — store e
dispatcher isolati via monkeypatch, stesso stampo di `test_alberatura.py`/
`test_scansioni.py`."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import treasureiq.connettore as connettore_mod
from treasureiq.catalog import recognition_adapter as recognition_adapter_mod
from treasureiq.connettore import (
    AmministrazioneTrasparente,
    AreaAmministrativa,
    EsitoConnettore,
    UfficioConnettore,
    _da_store,
    _esito_vuoto,
    _in_store,
    leggi_connettore,
    refresh_dati_connettore,
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
        recognition_adapter_mod, "firma_da_registro",
        lambda **_kw: Firma(
            piattaforma=Piattaforma.MUNICIPIUM, prova="municipium"
        ),
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


def test_refresh_dati_usa_la_piattaforma_in_cache_senza_firma_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    precedente = _esito(
        uffici=[
            UfficioConnettore(
                nome="Vecchio", url="https://x/vecchio", source_typed=True,
                letto_il="2026-01-01T00:00:00+00:00",
            )
        ],
        letto_il="2026-01-01T00:00:00+00:00",
    ).model_copy(update={"fonte_hash": "home-hash", "controllato_il": "2026-01-01T00:00:00+00:00"})
    _in_store(precedente)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaFinta)
    monkeypatch.setattr(recognition_adapter_mod, "firma_da_registro", lambda **kwargs: pytest.fail("non deve riconoscere la home"))
    monkeypatch.setattr(connettore_mod, "_esito_vuoto", lambda esito: False)
    monkeypatch.setattr("treasureiq.registro.registra_scansione", lambda comune, esito: None)

    aggiornato = precedente.model_copy(
        update={
            "letto_il": "2026-08-21T00:00:00+00:00",
            "uffici": [
                UfficioConnettore(
                    nome="Nuovo", url="https://x/nuovo", source_typed=True,
                    letto_il="2026-08-21T00:00:00+00:00",
                )
            ],
        }
    )
    fake_mod = types.ModuleType("treasureiq.municipium")
    fake_mod.leggi_municipium = lambda comune, sonda: aggiornato
    monkeypatch.setitem(sys.modules, "treasureiq.municipium", fake_mod)

    esito = refresh_dati_connettore(ISTAT)

    assert esito is not None
    assert esito.uffici[0].nome == "Nuovo"
    assert esito.fonte_hash == "home-hash"
    assert esito.controllato_il == precedente.controllato_il


# --- Dispatcher (deferred piattaforme, degrado muto) -------------------


def test_dispatcher_municipium_non_importabile_ritorna_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`treasureiq.municipium` non esiste ancora (B2): nessun crash, `None`."""
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaFinta)
    monkeypatch.setattr(
        recognition_adapter_mod, "firma_da_registro",
        lambda **_kw: Firma(
            piattaforma=Piattaforma.MUNICIPIUM, prova="municipium"
        ),
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
        recognition_adapter_mod, "firma_da_registro",
        lambda **_kw: Firma(
            piattaforma=Piattaforma.DRUPAL, prova="drupal"
        ),
    )

    assert leggi_connettore(ISTAT, usa_cache=False) is None


def test_dispatcher_comune_ignoto_ritorna_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: None)
    assert leggi_connettore("000000", usa_cache=False) is None


# --- Classificazione piattaforma AT (B5, ciclo16) -----------------------


def test_leggi_connettore_classifica_piattaforma_at_se_presente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """L'AT trovata dal connettore vendor viene classificata a parte
    (`scopri_pagina_at`, riusa l'HTML home già scaricato, un solo fetch
    extra per la pagina AT) — nessun connettore AT viene INVOCATO qui
    (NON-GOAL di questo brief), solo sapere quale piattaforma la serve."""
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaFinta)
    monkeypatch.setattr(
        recognition_adapter_mod, "firma_da_registro",
        lambda **_kw: Firma(
            piattaforma=Piattaforma.MUNICIPIUM, prova="municipium"
        ),
    )

    at_scoperta = AmministrazioneTrasparente(indice_url="https://x/at")
    fake_mod = types.ModuleType("treasureiq.municipium")
    fake_mod.leggi_municipium = lambda comune, sonda: _esito(
        uffici=[UfficioConnettore(
            nome="URP", url="https://www.comunefiv.it/urp",
            source_typed=True, letto_il=datetime.now(timezone.utc).isoformat(),
        )],
        at=at_scoperta,
    )
    monkeypatch.setitem(sys.modules, "treasureiq.municipium", fake_mod)

    finta_scoperta = SimpleNamespace(piattaforma_at=Piattaforma.JCITYGOV, at_url="https://x/at")
    monkeypatch.setattr(connettore_mod, "scopri_pagina_at", lambda *, html_home, base: finta_scoperta)

    esito = leggi_connettore(ISTAT, usa_cache=False)
    assert esito is not None
    assert esito.amministrazione_trasparente is not None
    assert esito.amministrazione_trasparente.piattaforma_at == Piattaforma.JCITYGOV.value


def test_leggi_connettore_at_non_trovata_non_classifica(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`scopri_pagina_at` che ritorna `NON_TROVATA` (nessuna ancora AT
    nella home riletta, o guardia SSRF che scarta la pagina) lascia
    `piattaforma_at` a `None` — nessuna piattaforma indovinata."""
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaFinta)
    monkeypatch.setattr(
        recognition_adapter_mod, "firma_da_registro",
        lambda **_kw: Firma(
            piattaforma=Piattaforma.MUNICIPIUM, prova="municipium"
        ),
    )

    at_scoperta = AmministrazioneTrasparente(indice_url="https://x/at")
    fake_mod = types.ModuleType("treasureiq.municipium")
    fake_mod.leggi_municipium = lambda comune, sonda: _esito(
        uffici=[UfficioConnettore(
            nome="URP", url="https://www.comunefiv.it/urp",
            source_typed=True, letto_il=datetime.now(timezone.utc).isoformat(),
        )],
        at=at_scoperta,
    )
    monkeypatch.setitem(sys.modules, "treasureiq.municipium", fake_mod)

    finta_scoperta = SimpleNamespace(piattaforma_at=Piattaforma.NON_TROVATA, at_url=None)
    monkeypatch.setattr(connettore_mod, "scopri_pagina_at", lambda *, html_home, base: finta_scoperta)

    esito = leggi_connettore(ISTAT, usa_cache=False)
    assert esito is not None
    assert esito.amministrazione_trasparente is not None
    assert esito.amministrazione_trasparente.piattaforma_at is None


def test_leggi_connettore_senza_at_non_classifica(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Esito senza AT (`amministrazione_trasparente is None`): nessun
    tentativo di classificazione — `scopri_pagina_at` non viene nemmeno
    chiamata (guardia esplicita in `leggi_connettore`)."""
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda codice: _comune())
    monkeypatch.setattr(connettore_mod, "_Sonda", _SondaFinta)
    monkeypatch.setattr(
        recognition_adapter_mod, "firma_da_registro",
        lambda **_kw: Firma(
            piattaforma=Piattaforma.MUNICIPIUM, prova="municipium"
        ),
    )

    fake_mod = types.ModuleType("treasureiq.municipium")
    fake_mod.leggi_municipium = lambda comune, sonda: _esito(
        uffici=[UfficioConnettore(
            nome="URP", url="https://www.comunefiv.it/urp",
            source_typed=True, letto_il=datetime.now(timezone.utc).isoformat(),
        )],
    )
    monkeypatch.setitem(sys.modules, "treasureiq.municipium", fake_mod)

    chiamata = []
    monkeypatch.setattr(
        connettore_mod, "scopri_pagina_at",
        lambda *, html_home, base: chiamata.append(1),
    )

    esito = leggi_connettore(ISTAT, usa_cache=False)
    assert esito is not None
    assert esito.amministrazione_trasparente is None
    assert chiamata == []
