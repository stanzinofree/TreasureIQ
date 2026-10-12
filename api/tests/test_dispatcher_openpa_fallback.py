"""Il dispatcher riusa il fallback OpenPA gia' validato dal censimento."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import treasureiq.connettore as connettore_mod
from treasureiq.connettore import EsitoConnettore, UfficioConnettore, leggi_connettore
from treasureiq.ingest.piattaforma import Firma, Piattaforma
from treasureiq.sonda_live import ComuneNoto

ISTAT = "097015"
_HOME_OPENPA = """
<html><head>
  <link href="/content/style.css" rel="stylesheet">
  <script src="/extension/openpa_bootstrapitalia/main.js"></script>
</head><body><a href="/Argomenti/Ambiente">Ambiente</a></body></html>
"""


class _Risposta:
    headers: dict[str, str] = {}
    text = _HOME_OPENPA


class _Sonda:
    def __init__(self, *, timeout: float = 8.0) -> None:
        self.timeout = timeout

    def __enter__(self) -> "_Sonda":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def risposta(self, url: str) -> _Risposta:
        return _Risposta()


def test_dispatcher_ignoto_con_impronta_openpa_usa_il_lettore_openpa(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comune = ComuneNoto(
        codice_istat=ISTAT,
        nome="Casargo",
        provincia="LC",
        regione="Lombardia",
        sito="www.comune.casargo.lc.it",
    )
    letto = UfficioConnettore(
        nome="Ufficio Tecnico",
        url="https://www.comune.casargo.lc.it/Amministrazione/Uffici/Ufficio-Tecnico",
        source_typed=True,
        letto_il=datetime.now(timezone.utc).isoformat(),
    )
    esito_openpa = EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma="openpa",
        letto_il=datetime.now(timezone.utc).isoformat(),
        uffici=[letto],
    )
    openpa_finto = types.ModuleType("treasureiq.openpa")
    openpa_finto.leggi_openpa = lambda _comune, _sonda: esito_openpa

    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda _codice: comune)
    monkeypatch.setattr(connettore_mod, "_Sonda", _Sonda)
    monkeypatch.setitem(sys.modules, "treasureiq.openpa", openpa_finto)
    monkeypatch.setattr("treasureiq.registro.registra_scansione", lambda _comune, _esito: None)

    esito = leggi_connettore(ISTAT, usa_cache=False)

    assert esito is not None
    assert esito.piattaforma == "openpa"
    assert esito.uffici == [letto]


def test_fallback_non_openpa_non_esclude_il_recupero_wordpress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from treasureiq.ingest import piattaforma

    comune = ComuneNoto(
        codice_istat=ISTAT,
        nome="Casargo",
        provincia="LC",
        regione="Lombardia",
        sito="www.comune.casargo.lc.it",
    )
    esito_wordpress = EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma="wordpress_generico",
        letto_il=datetime.now(timezone.utc).isoformat(),
    )
    wordpress_finto = types.ModuleType("treasureiq.wordpress_agid")
    wordpress_finto.leggi_wordpress_agid = lambda _comune, _sonda: esito_wordpress

    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda _codice: comune)
    monkeypatch.setattr(connettore_mod, "_Sonda", _Sonda)
    regioni: list[str | None] = []

    def _fallback_estraneo(**kwargs: object) -> Firma:
        regioni.append(kwargs["regione"])
        return Firma(Piattaforma.MAGNOLIA, "impronta estranea")

    monkeypatch.setattr(piattaforma, "da_impronta", _fallback_estraneo)
    monkeypatch.setattr(
        connettore_mod,
        "mappa_connettore",
        lambda _codice: SimpleNamespace(
            uffici=SimpleNamespace(esposto=True, rest_base="unita_organizzative")
        ),
    )
    monkeypatch.setitem(sys.modules, "treasureiq.wordpress_agid", wordpress_finto)
    monkeypatch.setattr("treasureiq.registro.registra_scansione", lambda _comune, _esito: None)

    esito = leggi_connettore(ISTAT, usa_cache=False)

    assert esito is not None
    assert esito.piattaforma == "wordpress_generico"
    assert regioni == ["Lombardia"]


def test_fallback_openpa_non_si_applica_a_una_piattaforma_gia_riconosciuta(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from treasureiq.ingest import piattaforma

    comune = ComuneNoto(
        codice_istat=ISTAT,
        nome="Casargo",
        provincia="LC",
        regione="Lombardia",
        sito="www.comune.casargo.lc.it",
    )
    esito_municipium = EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma="municipium",
        letto_il=datetime.now(timezone.utc).isoformat(),
    )
    municipium_finto = types.ModuleType("treasureiq.municipium")
    municipium_finto.leggi_municipium = lambda _comune, _sonda: esito_municipium

    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda _codice: comune)
    monkeypatch.setattr(connettore_mod, "_Sonda", _Sonda)
    monkeypatch.setattr(
        _Risposta,
        "text",
        '<script src="https://assets.municipiumapp.it/app.js"></script>',
    )
    monkeypatch.setattr(
        piattaforma,
        "da_impronta",
        lambda **_kwargs: pytest.fail("il fallback non deve girare dopo un riconoscimento"),
    )
    monkeypatch.setitem(sys.modules, "treasureiq.municipium", municipium_finto)
    monkeypatch.setattr("treasureiq.registro.registra_scansione", lambda _comune, _esito: None)

    esito = leggi_connettore(ISTAT, usa_cache=False)

    assert esito is not None
    assert esito.piattaforma == "municipium"
