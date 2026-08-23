"""Estrattori per famiglia di indirizzo/responsabile contro fixture reali.

Ogni caso è una scheda-dettaglio scaricata da un comune vero, una per forma di
DOM: openpa (Storo), openweb (Collegno), peopleweb vendor OpenWeb.NET (Airasca)
e vendor Siscom (Andrate), municipium (Pomezia). Verifica cosa la pagina
pubblica DAVVERO: nome+ruolo dove strutturati, `email` sempre `None`, indirizzo
= sede dell'ente. Piattaforma sconosciuta o campo assente → `None`, mai inventato.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treasureiq.ufficio_estrattori import estrai_indirizzo, estrai_responsabile

FIX = Path(__file__).parent / "fixtures"


def _pagina(nome: str) -> str:
    return (FIX / f"{nome}_ufficio_dettaglio.html").read_text("utf-8", errors="replace")


def _municipium() -> str:
    return (FIX / "municipium" / "ufficio_demografici.html").read_text("utf-8", errors="replace")


# --------------------------- responsabile --------------------------------- #


def test_responsabile_openpa_nome_e_ruolo() -> None:
    resp = estrai_responsabile(_pagina("openpa_storo"), piattaforma="openpa")
    assert resp is not None
    assert resp.nome == "Benedetta Moneghini"
    assert resp.ruolo == "Responsabile"
    assert resp.email is None


def test_responsabile_openweb_nome_e_ruolo() -> None:
    resp = estrai_responsabile(_pagina("openweb_collegno"), piattaforma="openweb")
    assert resp is not None
    assert resp.nome == "Enza Augelli"
    assert resp.ruolo == "Responsabile Servizi Demografici e Generali"
    assert resp.email is None


def test_responsabile_peopleweb_openweb_net_solo_nome() -> None:
    # Vendor OpenWeb.NET: la card espone il nome, non un ruolo strutturato.
    resp = estrai_responsabile(_pagina("peopleweb_airasca"), piattaforma="peopleweb")
    assert resp is not None
    assert resp.nome == "GRIOTTO Laura"
    assert resp.ruolo is None
    assert resp.email is None


def test_responsabile_peopleweb_siscom_preferisce_resp_su_dirigente() -> None:
    # Vendor Siscom: c'è sia il dirigente d'area sia il responsabile ufficio;
    # si prende il responsabile (#resp), non il dirigente.
    resp = estrai_responsabile(_pagina("peopleweb_andrate"), piattaforma="peopleweb")
    assert resp is not None
    assert resp.nome == "Manuela CHIAVETTO"
    assert resp.ruolo == "Responsabile"
    assert resp.email is None


def test_responsabile_municipium_nome_senza_ruolo() -> None:
    resp = estrai_responsabile(_municipium(), piattaforma="municipium")
    assert resp is not None
    assert resp.nome == "Angelo Pizzoli"
    assert resp.ruolo is None
    assert resp.email is None


def test_responsabile_piattaforma_sconosciuta_none() -> None:
    assert estrai_responsabile(_pagina("openpa_storo"), piattaforma="isweb") is None
    assert estrai_responsabile(_pagina("openpa_storo"), piattaforma=None) is None


def test_responsabile_pagina_muta_none() -> None:
    assert estrai_responsabile("<html><body>niente</body></html>", piattaforma="openpa") is None


# ---------------------------- indirizzo ----------------------------------- #


def test_indirizzo_openpa_sede() -> None:
    assert estrai_indirizzo(_pagina("openpa_storo"), piattaforma="openpa") == (
        "Piazza Europa, 5 - 38089 Storo (TN)"
    )


def test_indirizzo_openweb_sede_principale() -> None:
    ind = estrai_indirizzo(_pagina("openweb_collegno"), piattaforma="openweb")
    assert ind is not None
    assert "Piazza del Municipio 1" in ind
    assert "10093" in ind


def test_indirizzo_peopleweb_openweb_net_in_chiaro() -> None:
    ind = estrai_indirizzo(_pagina("peopleweb_airasca"), piattaforma="peopleweb")
    assert ind is not None
    assert "Via Roma, 118" in ind
    assert "10060" in ind


def test_indirizzo_peopleweb_siscom_dopo_etichetta() -> None:
    ind = estrai_indirizzo(_pagina("peopleweb_andrate"), piattaforma="peopleweb")
    assert ind == "Via della Parrocchia n. 18"


def test_indirizzo_municipium_postal_address() -> None:
    assert estrai_indirizzo(_municipium(), piattaforma="municipium") == (
        "Piazza Indipendenza, 8 - 00071 Pomezia (RM)"
    )


def test_indirizzo_piattaforma_sconosciuta_none() -> None:
    assert estrai_indirizzo(_pagina("openpa_storo"), piattaforma="isweb") is None
    assert estrai_indirizzo(_pagina("openpa_storo"), piattaforma=None) is None
