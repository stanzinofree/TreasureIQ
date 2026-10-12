from __future__ import annotations

import json
from html import escape
from types import SimpleNamespace

from treasureiq.agenda_smart import _contenuti_da_html, _uffici_da_html, leggi_agenda_smart


def test_uffici_da_payload_estrae_solo_schede_stesso_host() -> None:
    pagina = r'''<explore-info :contents="[{&quot;title&quot;:&quot;Ufficio Tecnico&quot;,&quot;share_url&quot;:&quot;https:\/\/comune.example.it\/uffici\/tecnico&quot;},{&quot;title&quot;:&quot;Esterno&quot;,&quot;share_url&quot;:&quot;https:\/\/altro.example.it\/uffici&quot;}]">'''

    uffici = _uffici_da_html(pagina, "https://comune.example.it/uffici", "comune.example.it", "2026-10-11T00:00:00+00:00")

    assert [(ufficio.nome, ufficio.url) for ufficio in uffici] == [("Ufficio Tecnico", "https://comune.example.it/uffici/tecnico")]


def test_contenuti_da_html_legge_il_totale_per_la_paginazione() -> None:
    assert _contenuti_da_html('<explore-info :contents="[]" total="51">') == ([], 51)


def test_leggi_agenda_smart_segue_le_pagine_degli_uffici() -> None:
    def pagina(titolo: str, totale: int) -> bytes:
        contenuti = [{"title": titolo, "share_url": f"https://comune.example.it/uffici/{titolo}"}]
        return f'<explore-info :contents="{escape(json.dumps(contenuti))}" total="{totale}">'.encode()

    chiamate: list[str] = []

    def fetch(url: str, **_kwargs):
        chiamate.append(url)
        return None, pagina("URP", 7) if "?page=" not in url else pagina("Tecnico", 7), url

    esito = leggi_agenda_smart(SimpleNamespace(codice_istat="999999", sito="https://comune.example.it"), SimpleNamespace(richieste=0, raggiungibile=False), fetch=fetch)

    assert [ufficio.nome for ufficio in esito.uffici] == ["URP", "Tecnico"]
    assert chiamate == ["https://comune.example.it/uffici", "https://comune.example.it/uffici?page=2"]


def test_leggi_agenda_smart_non_salva_un_indice_parziale() -> None:
    def fetch(url: str, **_kwargs):
        if "?page=" in url:
            return None, b"<main>pagina non valida</main>", url
        contenuti = [{"title": "URP", "share_url": "/uffici/urp"}]
        return None, f'<explore-info :contents="{escape(json.dumps(contenuti))}" total="7">'.encode(), url

    esito = leggi_agenda_smart(
        SimpleNamespace(codice_istat="999999", sito="https://comune.example.it"),
        SimpleNamespace(richieste=0, raggiungibile=False),
        fetch=fetch,
    )

    assert esito.uffici == []


def test_leggi_agenda_smart_non_salva_un_indice_oltre_il_cap() -> None:
    chiamate: list[str] = []

    def fetch(url: str, **_kwargs):
        chiamate.append(url)
        return None, b'<explore-info :contents="[]" total="201">', url

    esito = leggi_agenda_smart(SimpleNamespace(codice_istat="999999", sito="https://comune.example.it"), SimpleNamespace(richieste=0, raggiungibile=False), fetch=fetch)

    assert esito.uffici == []
    assert chiamate == ["https://comune.example.it/uffici"]
