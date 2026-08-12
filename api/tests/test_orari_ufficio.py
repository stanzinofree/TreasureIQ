"""Il lettore on-demand dell'orario di un ufficio nominato (ciclo18c).

Copre: estrazione dello slug, cache-first (positivo E negativo), degrado
onesto quando la pagina non pubblica un orario o è irraggiungibile, e il
wiring del rail informazione che sostituisce l'URP di ripiego con l'ufficio
giusto letto dal connettore.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import treasureiq.orari_ufficio as ou

URL_UFFICIO = (
    "https://comune.albanolaziale.rm.it/amministrazione/"
    "unita_organizzativa/ufficio-anagrafe-e-leva/"
)


def _stub_fetch(html: str, *, chiamate: list[str]):
    """Un `fetch_guardato` finto che conta le chiamate e torna l'HTML dato."""

    def finto(url, *, timeout, max_bytes, host_atteso=None):
        chiamate.append(url)
        return ({"content-type": "text/html; charset=utf-8"}, html.encode("utf-8"), url)

    return finto


# --- slug ---------------------------------------------------------------


def test_slug_da_url_prende_ultimo_segmento() -> None:
    assert ou._slug_da_url(URL_UFFICIO) == "ufficio-anagrafe-e-leva"


def test_slug_da_url_sanifica_caratteri_di_path() -> None:
    # Nessun separatore di path nello slug: è un nome di file.
    slug = ou._slug_da_url("https://x.it/a/b/Ufficio Tributi (sede)/")
    assert "/" not in slug and " " not in slug and slug


def test_url_non_http_ritorna_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ou, "LIVE_DIR", tmp_path)
    assert ou.leggi_orari_ufficio(codice_istat="058003", url="ftp://x.it/uff/") is None
    assert ou.leggi_orari_ufficio(codice_istat="058003", url="") is None


# --- lettura + cache ----------------------------------------------------


def test_pagina_con_orari_estrae_e_mette_in_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ou, "LIVE_DIR", tmp_path)
    chiamate: list[str] = []
    html = "<div>Orari: lunedì 9:00-12:30, giovedì 15:00-17:00</div>"
    monkeypatch.setattr(ou, "fetch_guardato", _stub_fetch(html, chiamate=chiamate))

    voce = ou.leggi_orari_ufficio(codice_istat="058003", url=URL_UFFICIO)
    assert voce is not None
    assert voce.orari == "Orari: lunedì 9:00-12:30, giovedì 15:00-17:00"
    assert voce.slug == "ufficio-anagrafe-e-leva"
    assert len(chiamate) == 1

    # Seconda chiamata: cache-hit, nessun fetch nuovo.
    voce2 = ou.leggi_orari_ufficio(codice_istat="058003", url=URL_UFFICIO)
    assert voce2 is not None and voce2.orari == voce.orari
    assert len(chiamate) == 1


def test_pagina_senza_orari_cache_negativa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ou, "LIVE_DIR", tmp_path)
    chiamate: list[str] = []
    monkeypatch.setattr(
        ou, "fetch_guardato", _stub_fetch("<p>Nessun orario qui</p>", chiamate=chiamate)
    )

    voce = ou.leggi_orari_ufficio(codice_istat="058003", url=URL_UFFICIO)
    assert voce is not None and voce.orari is None  # ufficio giusto, orario assente
    # Anche il negativo va in cache: non si ri-sonda il comune a ogni domanda.
    ou.leggi_orari_ufficio(codice_istat="058003", url=URL_UFFICIO)
    assert len(chiamate) == 1


def test_pagina_irraggiungibile_degrada_a_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ou, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(ou, "fetch_guardato", lambda *a, **k: None)
    voce = ou.leggi_orari_ufficio(codice_istat="058003", url=URL_UFFICIO)
    assert voce is not None and voce.orari is None


def test_cache_stantia_rilegge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ou, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(ou, "GIORNI_VALIDITA", 0)  # tutto è subito stantio
    chiamate: list[str] = []
    monkeypatch.setattr(
        ou, "fetch_guardato", _stub_fetch("<div>Orari: martedì 9-12</div>", chiamate=chiamate)
    )
    ou.leggi_orari_ufficio(codice_istat="058003", url=URL_UFFICIO)
    ou.leggi_orari_ufficio(codice_istat="058003", url=URL_UFFICIO)
    assert len(chiamate) == 2  # cache scaduta → seconda lettura


# --- wiring del rail informazione ---------------------------------------


def test_office_da_ufficio_nominato_sostituisce_urp(monkeypatch: pytest.MonkeyPatch) -> None:
    import treasureiq.chat.respond as respond
    from treasureiq.connettore import EsitoConnettore, UfficioConnettore
    from treasureiq.chat.intent import Topic

    ufficio = UfficioConnettore(
        nome="Ufficio Anagrafe e Leva",
        url=URL_UFFICIO,
        telefoni=["06 12345"],
        email=["anagrafe@comune.it"],
        pec=[],
        orari=None,
        source_typed=True,
        letto_il="2026-08-12T00:00:00+00:00",
    )
    esito = EsitoConnettore(
        codice_istat="058003",
        piattaforma="wordpress_agid",
        letto_il="2026-08-12T00:00:00+00:00",
        aree_amministrative=[],
        uffici=[ufficio],
        amministrazione_trasparente=None,
        endpoints={},
    )
    monkeypatch.setattr(respond.connettore, "leggi_connettore", lambda istat: esito)
    monkeypatch.setattr(
        respond,
        "leggi_orari_ufficio",
        lambda *, codice_istat, url: ou.OrariUfficio(
            codice_istat=codice_istat,
            slug="ufficio-anagrafe-e-leva",
            url=url,
            orari="Orari: lunedì 9-12",
            letto_il="2026-08-12T00:00:00+00:00",
        ),
    )

    office = asyncio.run(
        respond._office_da_ufficio_nominato(
            codice_istat="058003",
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            ufficio_chiesto="anagrafe",
            disabilita_attiva=False,
        )
    )
    assert office is not None
    assert office.nome == "Ufficio Anagrafe e Leva"
    assert office.orari == "Orari: lunedì 9-12"
    assert office.telefono == "06 12345"


def test_office_da_ufficio_nominato_letterale_vince_su_sinonimi_ambigui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Caso Albano: «anagrafe» via sinonimi (stato civile/demografic) colpisce
    # più uffici → il matcher generale direbbe «ambiguo». Ma la parola
    # letterale sta in un solo nome: quello va scelto, non l'URP.
    import treasureiq.chat.respond as respond
    from treasureiq.connettore import EsitoConnettore, UfficioConnettore
    from treasureiq.chat.intent import Topic

    def _uff(nome: str, url: str) -> UfficioConnettore:
        return UfficioConnettore(
            nome=nome, url=url, telefoni=[], email=[], pec=[], orari=None,
            source_typed=True, letto_il="2026-08-12T00:00:00+00:00",
        )

    esito = EsitoConnettore(
        codice_istat="058003",
        piattaforma="wordpress_agid",
        letto_il="2026-08-12T00:00:00+00:00",
        aree_amministrative=[],
        uffici=[
            _uff("Ufficio Anagrafe e Leva", URL_UFFICIO),
            _uff("Ufficio Stato Civile, Elettorale", "https://comune.albanolaziale.rm.it/x/"),
        ],
        amministrazione_trasparente=None,
        endpoints={},
    )
    monkeypatch.setattr(respond.connettore, "leggi_connettore", lambda istat: esito)
    monkeypatch.setattr(
        respond, "leggi_orari_ufficio",
        lambda *, codice_istat, url: ou.OrariUfficio(
            codice_istat=codice_istat, slug="s", url=url,
            orari="Orari: lunedì 9-12", letto_il="2026-08-12T00:00:00+00:00",
        ),
    )
    office = asyncio.run(
        respond._office_da_ufficio_nominato(
            codice_istat="058003", topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            ufficio_chiesto="anagrafe", disabilita_attiva=False,
        )
    )
    assert office is not None and office.nome == "Ufficio Anagrafe e Leva"


def test_office_da_ufficio_nominato_none_se_connettore_muto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import treasureiq.chat.respond as respond
    from treasureiq.chat.intent import Topic

    monkeypatch.setattr(respond.connettore, "leggi_connettore", lambda istat: None)
    office = asyncio.run(
        respond._office_da_ufficio_nominato(
            codice_istat="058003",
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            ufficio_chiesto="anagrafe",
            disabilita_attiva=False,
        )
    )
    assert office is None
