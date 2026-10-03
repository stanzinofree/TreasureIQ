"""Tests for `unita_tipizzate`: AgID unit types from the WordPress REST
taxonomy. No network: a fake sonda answers by URL. Term ids differ per site
(Lesa: area=234, Cuneo: area=235), so the fakes use different ids on purpose.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from treasureiq.unita_tipizzate import AREA, FUORI, UFFICIO, leggi_unita_tipizzate

_BASE = "https://www.comune.esempio.it"


def _termini(**ids: int) -> list[dict]:
    return [{"id": term_id, "slug": slug.replace("_", "-")} for slug, term_id in ids.items()]


def _unita(nome: str, *tipi: int) -> dict:
    return {
        "title": {"rendered": nome},
        "link": f"{_BASE}/amministrazione/unita_organizzativa/{nome.lower().replace(' ', '-')}/",
        "tipi_unita_organizzativa": list(tipi),
    }


class _Sonda:
    def __init__(self, termini: object, pagine: list[list[dict]]) -> None:
        self.termini = termini
        self.pagine = pagine
        self.url_chiesti: list[str] = []

    def json(self, url: str) -> object:
        self.url_chiesti.append(url)
        if "/tipi_unita_organizzativa" in url:
            if isinstance(self.termini, Exception):
                raise self.termini
            return self.termini
        pagina = int(parse_qs(urlparse(url).query).get("page", ["1"])[0])
        if pagina > len(self.pagine):
            raise RuntimeError("rest_post_invalid_page_number")  # what WordPress answers (400)
        return self.pagine[pagina - 1]


def test_classifica_per_slug_letto_dal_sito() -> None:
    termini = _termini(area=235, ufficio=236, giunta_comunale=238, ente=245, biblioteca=242)
    sonda = _Sonda(termini, [[
        _unita("Area Tecnica", 235),
        _unita("Anagrafe", 236),
        _unita("Giunta Comunale", 238),
        _unita("Consorzio Rifiuti", 245),
        _unita("Biblioteca Civica", 242),
        _unita("Senza tipo"),
    ]])

    unita = leggi_unita_tipizzate(sonda, _BASE, "unita_organizzative")

    assert unita is not None
    assert [(u.nome, u.categoria) for u in unita] == [
        ("Area Tecnica", AREA),
        ("Anagrafe", UFFICIO),
        ("Giunta Comunale", FUORI),
        ("Consorzio Rifiuti", FUORI),
        ("Biblioteca Civica", UFFICIO),  # places citizens contact stay offices
        ("Senza tipo", UFFICIO),         # untyped keeps today's behaviour
    ]


def test_ufficio_vince_su_altri_tipi_e_slug_ignoto_resta_ufficio() -> None:
    termini = _termini(area=1, ufficio=2, commissione=3, nuovo_tipo_mai_visto=4)
    sonda = _Sonda(termini, [[
        _unita("Ufficio e area", 1, 2),
        _unita("Commissione mensa", 3),
        _unita("Tipo nuovo", 4),
    ]])

    unita = leggi_unita_tipizzate(sonda, _BASE, "unita_organizzative")

    assert [u.categoria for u in unita] == [UFFICIO, FUORI, UFFICIO]


def test_pagina_oltre_la_prima_finche_il_sito_risponde() -> None:
    termini = _termini(ufficio=9)
    prima = [_unita(f"Ufficio {n}", 9) for n in range(100)]
    seconda = [_unita("Ufficio extra", 9)]
    sonda = _Sonda(termini, [prima, seconda])

    unita = leggi_unita_tipizzate(sonda, _BASE, "unita_organizzative")

    assert len(unita) == 101
    assert any("page=2" in url for url in sonda.url_chiesti)
    assert not any("page=3" in url for url in sonda.url_chiesti)  # short page = last


def test_senza_tassonomia_ritorna_none() -> None:
    """No taxonomy (error, or rows without slugs) means "cannot tell":
    callers keep their current behaviour."""
    assert leggi_unita_tipizzate(_Sonda(RuntimeError("404"), [[]]), _BASE, "x") is None
    righe_senza_slug = [{"title": {"rendered": "Tributi"}, "link": f"{_BASE}/t/"}]
    assert leggi_unita_tipizzate(_Sonda(righe_senza_slug, [righe_senza_slug]), _BASE, "x") is None


def test_unita_senza_titolo_o_link_scartate_e_dedup_per_url() -> None:
    termini = _termini(ufficio=1)
    doppia = _unita("Tributi", 1)
    sonda = _Sonda(termini, [[doppia, dict(doppia), {"title": {"rendered": ""}, "link": "x"}, {"link": "y"}]])

    unita = leggi_unita_tipizzate(sonda, _BASE, "unita_organizzative")

    assert [u.nome for u in unita] == ["Tributi"]
