"""Tests for `unita_tipizzate`: AgID unit types from the WordPress REST
taxonomy. No network: a fake sonda answers by URL. Term ids differ per site
(Lesa: area=234, Cuneo: area=235), so the fakes use different ids on purpose.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from treasureiq.unita_tipizzate import AREA, FUORI, UFFICIO, LetturaIncompleta, leggi_unita_tipizzate

_BASE = "https://www.comune.esempio.it"


def _http(stato: int, codice: str | None = None) -> httpx.HTTPStatusError:
    richiesta = httpx.Request("GET", _BASE)
    corpo = {"code": codice, "message": "x", "data": {"status": stato}} if codice else None
    risposta = httpx.Response(stato, request=richiesta, json=corpo) if corpo else httpx.Response(stato, request=richiesta)
    return httpx.HTTPStatusError(str(stato), request=richiesta, response=risposta)


#: What WordPress really answers past the last page.
_FINE_WP = "rest_post_invalid_page_number"


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
            raise _http(400, _FINE_WP)  # the valid end, with WordPress' own code
        blocco = self.pagine[pagina - 1]
        if isinstance(blocco, BaseException):
            raise blocco
        return blocco


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
    assert leggi_unita_tipizzate(_Sonda(_http(404), [[]]), _BASE, "x") is None
    righe_senza_slug = [{"title": {"rendered": "Tributi"}, "link": f"{_BASE}/t/"}]
    assert leggi_unita_tipizzate(_Sonda(righe_senza_slug, [righe_senza_slug]), _BASE, "x") is None


def test_unita_senza_titolo_o_link_scartate_e_dedup_per_url() -> None:
    termini = _termini(ufficio=1)
    doppia = _unita("Tributi", 1)
    sonda = _Sonda(termini, [[doppia, dict(doppia), {"title": {"rendered": ""}, "link": "x"}, {"link": "y"}]])

    unita = leggi_unita_tipizzate(sonda, _BASE, "unita_organizzative")

    assert [u.nome for u in unita] == ["Tributi"]


# --- absence vs outage: an outage must never look like "no taxonomy" ------


@pytest.mark.parametrize("guasto", [httpx.ReadTimeout("t"), _http(429), _http(503)])
def test_tassonomia_indisponibile_non_e_tassonomia_assente(guasto: BaseException) -> None:
    """QA repro: a taxonomy timeout fell back to the untyped list and put the
    Giunta back among the offices."""
    with pytest.raises(LetturaIncompleta):
        leggi_unita_tipizzate(_Sonda(guasto, [[_unita("Anagrafe", 1)]]), _BASE, "unita_organizzative")


@pytest.mark.parametrize("guasto", [httpx.ReadTimeout("t"), _http(429), _http(502)])
def test_pagina_successiva_indisponibile_e_lettura_incompleta(guasto: BaseException) -> None:
    """QA repro: page 2 timing out returned page 1 alone as if complete."""
    prima = [_unita(f"Ufficio {n}", 9) for n in range(100)]
    with pytest.raises(LetturaIncompleta):
        leggi_unita_tipizzate(_Sonda(_termini(ufficio=9), [prima, guasto]), _BASE, "unita_organizzative")


def test_prima_pagina_indisponibile_e_lettura_incompleta() -> None:
    with pytest.raises(LetturaIncompleta):
        leggi_unita_tipizzate(_Sonda(_termini(ufficio=9), [httpx.ConnectError("x")]), _BASE, "x")


def test_pagina_piena_seguita_da_400_e_la_fine_valida() -> None:
    prima = [_unita(f"Ufficio {n}", 9) for n in range(100)]
    unita = leggi_unita_tipizzate(_Sonda(_termini(ufficio=9), [prima]), _BASE, "unita_organizzative")
    assert len(unita) == 100


@pytest.mark.parametrize(
    "seconda",
    [
        _http(400, "rest_invalid_param"),        # a 400 that is not the end
        _http(400),                              # a 400 with no WordPress code
        {"code": "unexpected_error"},            # an error object served with 200
    ],
)
def test_dopo_pagina_piena_solo_la_fine_wp_comprovata_chiude(seconda: object) -> None:
    """QA addendum: only `rest_post_invalid_page_number` proves the end."""

    class _SondaSeconda(_Sonda):
        def json(self, url: str) -> object:
            if "page=2" in url:
                if isinstance(seconda, BaseException):
                    raise seconda
                return seconda
            return super().json(url)

    prima = [_unita(f"Ufficio {n}", 9) for n in range(100)]
    with pytest.raises(LetturaIncompleta):
        leggi_unita_tipizzate(_SondaSeconda(_termini(ufficio=9), [prima]), _BASE, "unita_organizzative")


def test_prima_pagina_non_elenco_e_lettura_incompleta() -> None:
    with pytest.raises(LetturaIncompleta):
        leggi_unita_tipizzate(_Sonda(_termini(ufficio=9), [{"code": "unexpected_error"}]), _BASE, "x")


def test_collezione_unita_inesistente_resta_non_tipizzata() -> None:
    """Taxonomy present but no unit collection at this rest_base (404 on
    page 1): absent, so the caller keeps its untyped path."""
    assert leggi_unita_tipizzate(_Sonda(_termini(ufficio=9), [_http(404)]), _BASE, "x") is None



@pytest.mark.parametrize(
    "prima", [_http(400, "rest_invalid_param"), _http(400), ValueError("Expecting value")]
)
def test_prima_pagina_in_errore_non_e_collezione_assente(prima: BaseException) -> None:
    """QA addendum 2: only a definitive refusal (401/403/404/410) means the
    collection is absent; anything else on page 1 is an incomplete read."""
    with pytest.raises(LetturaIncompleta):
        leggi_unita_tipizzate(_Sonda(_termini(ufficio=9), [prima]), _BASE, "x")


@pytest.mark.parametrize("stato", [401, 403, 410])
def test_rest_negato_resta_non_tipizzato(stato: int) -> None:
    """A site that refuses REST for good keeps the untyped path instead of
    never being updated again."""
    assert leggi_unita_tipizzate(_Sonda(_termini(ufficio=9), [_http(stato)]), _BASE, "x") is None
    assert leggi_unita_tipizzate(_Sonda(_http(stato), [[]]), _BASE, "x") is None


def test_tassonomia_400_e_lettura_incompleta() -> None:
    with pytest.raises(LetturaIncompleta):
        leggi_unita_tipizzate(_Sonda(_http(400, "rest_invalid_param"), [[]]), _BASE, "x")
