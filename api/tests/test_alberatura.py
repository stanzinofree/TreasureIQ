"""Test di `alberatura.py` (ciclo 8, brief B1): niente rete — fixture reali
salvate il 2026-08-08 da Figline e Incisa Valdarno (WP) e Benevento (Halley).
I probe dal vivo sono nel VERIFY del brief, non qui (D-15-style: unit test
deterministici, probe live a parte)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from treasureiq.alberatura import (
    RamoAT,
    _ancore,
    _bandi_da_listing_halley,
    _da_cache,
    _decodifica,
    _estrai_wp,
    _in_cache,
    _rami_da_pagina,
    _rami_wp,
    _tipo_da_slug,
    _tipo_da_testo,
    estrai_bandi,
    scopri_rami,
)
from treasureiq.sonda_live import ComuneNoto

FIXTURES = Path(__file__).parent / "fixtures" / "alberatura"

BASE_FIGLINE = "https://www.comunefiv.it"
BASE_BENEVENTO = "https://www.comune.benevento.it"


class _RispostaFinta:
    """Un doppio minimale di `httpx.Response`: solo i campi che
    `alberatura.py` legge (`status_code`, `headers`, `content`, `url`)."""

    def __init__(
        self, status_code: int, content: bytes, headers: dict[str, str] | None = None, url: str = ""
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.url = url


class _SondaFinta:
    """Stesso stampo di `test_mappa_connettore.py`: url attesa -> risposta
    fissa. Un url non prevista è un errore di test, non un `None` silenzioso."""

    def __init__(
        self,
        json_per_url: dict[str, object] | None = None,
        risposta_per_url: dict[str, _RispostaFinta] | None = None,
    ) -> None:
        self._json = json_per_url or {}
        self._risposte = risposta_per_url or {}

    def json(self, url: str, **_params: object) -> object:
        assert url in self._json, f"url non prevista nel fake: {url}"
        return self._json[url]

    def risposta(self, url: str) -> _RispostaFinta:
        assert url in self._risposte, f"url non prevista nel fake: {url}"
        return self._risposte[url]


def _leggi_json(nome: str) -> object:
    return json.loads((FIXTURES / nome).read_text("utf-8"))


def _leggi_bytes(nome: str) -> bytes:
    return (FIXTURES / nome).read_bytes()


# --- Matching tollerante -----------------------------------------------


def test_tipo_da_slug_riconosce_le_varianti_note() -> None:
    assert _tipo_da_slug("bandi-di-concorso") == "concorso"
    assert _tipo_da_slug("criteri-e-modalita") == "agevolazione"
    assert _tipo_da_slug("sovvenzioni-contributi-sussidi") == "agevolazione"
    assert _tipo_da_slug("194") is None  # id numerico Halley: non decide


def test_tipo_da_testo_tollera_maiuscole_e_accenti() -> None:
    assert _tipo_da_testo("CRITERI E MODALITÀ") == "agevolazione"
    assert _tipo_da_testo("Bandi di Concorso attivi") == "concorso"
    assert _tipo_da_testo("Bilanci") is None


# --- Ancore --------------------------------------------------------------


def test_ancore_scarta_placeholder_nascosti_e_non_http() -> None:
    pagina = (
        "<a href='#' target='_self'>Sovvenzioni</a>"
        "<a style='display:none!important;' href='/x'>Sovvenzioni</a>"
        "<a href='mailto:info@comune.it'>Scrivici</a>"
        "<a href='/zf/index.php/bandi-di-concorso'>Bandi di concorso attivi</a>"
    )
    ancore = _ancore(pagina)
    assert ancore == [("/zf/index.php/bandi-di-concorso", "Bandi di concorso attivi")]


# --- Gradino HTML (Halley/Benevento) -------------------------------------


def test_rami_da_pagina_benevento_trova_i_due_rami_giusti() -> None:
    pagina = _leggi_bytes("benevento_menu_at.html").decode("windows-1252")
    rami = _rami_da_pagina(BASE_BENEVENTO, pagina)
    per_tipo = {r.tipo: r for r in rami}

    assert per_tipo["concorso"].etichetta == "Bandi di concorso attivi"
    assert per_tipo["concorso"].url == "https://web.comune.benevento.it/zf/index.php/bandi-di-concorso"

    assert per_tipo["agevolazione"].etichetta == "Criteri e modalità"
    assert per_tipo["agevolazione"].url.endswith("/categoria/118")


def test_bandi_da_listing_halley_decodifica_gli_accenti() -> None:
    pagina = _leggi_bytes("benevento_listing_concorsi.html").decode("windows-1252")
    trovati = _bandi_da_listing_halley(pagina, "web.comune.benevento.it", "concorso")

    assert len(trovati) == 2
    titoli = [b.bando.titolo for b in trovati]
    assert any("mobilità" in t for t in titoli)  # A6: mai "mobilitÃ " o "mobilit�"
    assert all("&agrave;" not in t and "Ã " not in t for t in titoli)
    assert trovati[0].bando.data == "2026-07-06"  # F-1: dd/mm/yyyy -> ISO
    assert trovati[0].vendor == "halley"
    assert trovati[0].tipo == "concorso"
    assert trovati[0].bando.url.startswith("https://web.comune.benevento.it/")


def test_bandi_da_listing_halley_giorno_ambiguo_normalizza_iso() -> None:
    """F-1: giorno <=12 (05/03/2026) e' l'ambiguita' MM/DD vs DD/MM che
    `new Date(iso)` lato web risolve male se la stringa resta dd/mm/yyyy —
    deve uscire gia' ISO `YYYY-MM-DD`, mai il testo grezzo del portale."""
    pagina = (
        "<table><tbody>"
        "<tr data-href='https://web.comune.benevento.it/zf/index.php/dettaglio/1'>"
        "<td><a href='/zf/index.php/dettaglio/1'>Bando concorso</a></td>"
        "<td>05/03/2026</td>"
        "</tr>"
        "</tbody></table>"
    )
    trovati = _bandi_da_listing_halley(pagina, "web.comune.benevento.it", "concorso")
    assert len(trovati) == 1
    assert trovati[0].bando.data == "2026-03-05"


def test_bandi_da_listing_halley_scarta_dettaglio_fuori_host() -> None:
    """A7: un `<tr data-href>` che punta a un host diverso dal listing letto
    non è mai stato trovato navigando da lì — si scarta, non si segue."""
    pagina = (
        "<table><tbody>"
        "<tr data-href='https://evil.example.com/dettaglio/1'>"
        "<td><a href='https://evil.example.com/dettaglio/1'>Bando sospetto</a></td>"
        "<td>01/01/2027</td>"
        "</tr>"
        "</tbody></table>"
    )
    trovati = _bandi_da_listing_halley(pagina, "web.comune.benevento.it", "concorso")
    assert trovati == []


def test_decodifica_charset_dichiarato() -> None:
    risposta = _RispostaFinta(
        200, "mobilità".encode("windows-1252"), headers={"content-type": "text/html; charset=ISO-8859-1"}
    )
    assert _decodifica(risposta) == "mobilità"


def test_decodifica_ripiega_su_iso_8859_1_senza_charset() -> None:
    risposta = _RispostaFinta(200, "città".encode("iso-8859-1"), headers={})
    assert _decodifica(risposta) == "città"


# --- Gradino WP REST (Figline) -------------------------------------------


def test_rami_wp_figline_risolve_gli_slug_reali() -> None:
    sonda = _SondaFinta(
        json_per_url={
            f"{BASE_FIGLINE}/wp-json/wp/v2/taxonomies": _leggi_json("figline_taxonomies.json"),
            f"{BASE_FIGLINE}/wp-json/wp/v2/tipologie"
            "?per_page=100&_fields=id,name,count,slug": _leggi_json("figline_tipologie.json"),
        }
    )
    rami = _rami_wp(sonda, BASE_FIGLINE)
    assert rami is not None
    per_tipo = {r.tipo: r for r in rami}

    assert per_tipo["concorso"].etichetta == "Bandi di Concorso"
    assert "tipologie=449" in per_tipo["concorso"].url
    assert "/wp-json/wp/v2/amm-trasparente" in per_tipo["concorso"].url

    assert per_tipo["agevolazione"].etichetta == "Criteri e modalità"
    assert "tipologie=466" in per_tipo["agevolazione"].url


def test_rami_wp_nessuna_tassonomia_ritorna_none() -> None:
    sonda = _SondaFinta(json_per_url={f"{BASE_FIGLINE}/wp-json/wp/v2/taxonomies": {}})
    assert _rami_wp(sonda, BASE_FIGLINE) is None


def test_estrai_wp_figline_produce_bandi_scoperti_verbatim() -> None:
    ramo = RamoAT(
        etichetta="Bandi di Concorso",
        url=f"{BASE_FIGLINE}/wp-json/wp/v2/amm-trasparente?tipologie=449&per_page=20"
        "&_fields=title,link,date,excerpt,content&orderby=date&order=desc",
        tipo="concorso",
    )
    sonda = _SondaFinta(json_per_url={ramo.url: _leggi_json("figline_concorso.json")})
    trovati = _estrai_wp(sonda, BASE_FIGLINE, ramo)

    assert len(trovati) == 2
    assert all(b.vendor == "wp" and b.tipo == "concorso" for b in trovati)
    assert all(b.bando.titolo for b in trovati)
    assert all(b.bando.url.startswith(BASE_FIGLINE) for b in trovati)


# --- Cache (stampo bandi_live) --------------------------------------------


def test_cache_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import treasureiq.alberatura as alberatura_mod

    monkeypatch.setattr(alberatura_mod, "CACHE_DIR", tmp_path / "alberatura")
    ramo = RamoAT(etichetta="x", url=f"{BASE_FIGLINE}/wp-json/wp/v2/amm-trasparente?x=1", tipo="concorso")
    sonda = _SondaFinta(json_per_url={ramo.url: _leggi_json("figline_concorso.json")})
    bandi = _estrai_wp(sonda, BASE_FIGLINE, ramo)

    assert _da_cache("048052") is None
    _in_cache("048052", bandi)
    dalla_cache = _da_cache("048052")
    assert dalla_cache is not None
    assert len(dalla_cache) == len(bandi)
    assert dalla_cache[0].bando.titolo == bandi[0].bando.titolo


def test_cache_non_scrive_esito_vuoto(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`estrai_bandi` non deve mai fissare su disco una lista vuota."""
    import treasureiq.alberatura as alberatura_mod

    monkeypatch.setattr(alberatura_mod, "CACHE_DIR", tmp_path / "alberatura")
    ramo = RamoAT(etichetta="x", url=f"{BASE_FIGLINE}/wp-json/wp/v2/amm-trasparente?x=1", tipo="concorso")
    monkeypatch.setattr(alberatura_mod, "scopri_rami", lambda codice_istat, *, timeout=8.0: [ramo])
    monkeypatch.setattr(alberatura_mod, "_estrai_ramo", lambda sonda, base, ramo: [])
    monkeypatch.setattr(
        alberatura_mod,
        "comune_per_codice",
        lambda codice: ComuneNoto(
            codice_istat="048052", nome="Figline", provincia="FI", regione="Toscana", sito="www.comunefiv.it"
        ),
    )
    risultato = estrai_bandi("048052")
    assert risultato == []
    assert alberatura_mod._da_cache("048052") is None


# --- Contratto pubblico: scopri_rami/estrai_bandi senza rete --------------


def test_scopri_rami_none_se_comune_ignoto(monkeypatch: pytest.MonkeyPatch) -> None:
    import treasureiq.alberatura as alberatura_mod

    monkeypatch.setattr(alberatura_mod, "comune_per_codice", lambda codice: None)
    assert scopri_rami("000000") is None


def test_estrai_bandi_none_se_scopri_rami_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import treasureiq.alberatura as alberatura_mod

    monkeypatch.setattr(alberatura_mod, "_da_cache", lambda codice: None)
    monkeypatch.setattr(alberatura_mod, "scopri_rami", lambda codice_istat, *, timeout=8.0: None)
    assert estrai_bandi("048052") is None


def test_estrai_bandi_none_se_rami_di_vendor_non_gestito(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4: rami scoperti ma tutti su vendor senza estrattore (openweb,
    PeopleWeb, Plone...) -> `None`, non `[]` — altrimenti un comune non
    supportato appare "coperto senza bandi" invece di "non coperto"."""
    import treasureiq.alberatura as alberatura_mod

    ramo = RamoAT(etichetta="Bandi", url="https://www.comune.esempio.it/albo/bandi", tipo="concorso")
    monkeypatch.setattr(alberatura_mod, "_da_cache", lambda codice: None)
    monkeypatch.setattr(alberatura_mod, "scopri_rami", lambda codice_istat, *, timeout=8.0: [ramo])
    assert estrai_bandi("048052") is None


# --- ciclo18a B1: semina da `registro.endpoints.at` + cache dedicata rami ---

_COMUNE_BENEVENTO = ComuneNoto(
    codice_istat="062009", nome="Benevento", provincia="BN", regione="Campania", sito=BASE_BENEVENTO
)

#: Pagina AT catalogata su un host DIVERSO da `comune.sito` (SaaS fuori dal
#: dominio del comune) — dimostra che `base` per gli href relativi è
#: derivato da `url_finale`, mai da `comune.sito` (NOTA 3 del brief).
_AT_URL_FUORI_HOST = "https://trasparenza-esempio.saas.it/amministrazione-trasparente/"


def _rifiuta_chiamata(*args: object, **kwargs: object) -> None:
    raise AssertionError("non doveva essere chiamata")


def test_scopri_rami_semina_da_endpoints_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D-01/D-06: con `endpoints.at` catalogato, `scopri_rami` fetcha SOLO
    quella pagina (via `fetch_guardato`, guardia host intera) e non tocca
    `_rami_wp`/`_rami_html` — niente ripartenza dalla home. `base` per gli
    href relativi è l'host della pagina AT realmente raggiunta (fixture
    `benevento_menu_at.html`, off-host rispetto a `comune.sito`)."""
    import treasureiq.alberatura as alberatura_mod

    monkeypatch.setattr(alberatura_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(alberatura_mod, "comune_per_codice", lambda codice: _COMUNE_BENEVENTO)
    monkeypatch.setattr(
        "treasureiq.registro.leggi_registro",
        lambda codice: SimpleNamespace(endpoints=SimpleNamespace(at=_AT_URL_FUORI_HOST)),
    )
    monkeypatch.setattr(alberatura_mod, "_rami_wp", _rifiuta_chiamata)
    monkeypatch.setattr(alberatura_mod, "_rami_html", _rifiuta_chiamata)

    pagina = _leggi_bytes("benevento_menu_at.html")

    def _fetch_guardato_finto(url: str, *, timeout: float, max_bytes: int, host_atteso: str | None):
        assert url == _AT_URL_FUORI_HOST
        assert host_atteso == "trasparenza-esempio.saas.it"
        return httpx.Headers({"content-type": "text/html; charset=windows-1252"}), pagina, url

    monkeypatch.setattr(alberatura_mod, "fetch_guardato", _fetch_guardato_finto)

    rami = scopri_rami("062009")

    assert rami is not None
    assert len(rami) == 2
    per_tipo = {ramo.tipo: ramo for ramo in rami}
    # concorso: ancora già assoluta nella fixture, host suo (Benevento)
    assert per_tipo["concorso"].url == (
        "https://web.comune.benevento.it/zf/index.php/bandi-di-concorso"
    )
    # agevolazione: ancora relativa, risolta contro l'host della pagina AT
    # effettivamente raggiunta (fuori dal dominio del comune) — NOTA 3
    assert per_tipo["agevolazione"].url.startswith("https://trasparenza-esempio.saas.it")
    assert per_tipo["agevolazione"].url.endswith("/categoria/118")

    # persistenza (D-05): il seme finisce in cache dedicata rami.json
    assert (tmp_path / "062009" / "rami.json").exists()


def test_scopri_rami_endpoints_at_assente_usa_catena_originale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D-02: registro muto/senza `at` -> la catena originale (home del
    comune) resta invariata, e `fetch_guardato` non viene mai chiamato."""
    import treasureiq.alberatura as alberatura_mod

    comune_figline = ComuneNoto(
        codice_istat="048052", nome="Figline", provincia="FI", regione="Toscana", sito=BASE_FIGLINE
    )
    ramo_wp = RamoAT(etichetta="Bandi", url=f"{BASE_FIGLINE}/wp-json/wp/v2/amm-trasparente?x=1", tipo="concorso")

    monkeypatch.setattr(alberatura_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(alberatura_mod, "comune_per_codice", lambda codice: comune_figline)
    monkeypatch.setattr(
        "treasureiq.registro.leggi_registro",
        lambda codice: SimpleNamespace(endpoints=SimpleNamespace(at=None)),
    )
    monkeypatch.setattr(alberatura_mod, "fetch_guardato", _rifiuta_chiamata)
    monkeypatch.setattr(alberatura_mod, "_rami_wp", lambda sonda, base: [ramo_wp])
    monkeypatch.setattr(alberatura_mod, "_rami_html", _rifiuta_chiamata)

    rami = scopri_rami("048052")

    assert rami == [ramo_wp]


def test_scopri_rami_json_caldo_zero_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Cache `rami.json` calda: zero rete, zero lettura registro, zero
    lookup comune — la cache dedicata risponde da sola."""
    import treasureiq.alberatura as alberatura_mod

    ramo = RamoAT(etichetta="x", url=f"{BASE_FIGLINE}/wp-json/wp/v2/amm-trasparente?x=1", tipo="concorso")
    monkeypatch.setattr(alberatura_mod, "CACHE_DIR", tmp_path)
    alberatura_mod._rami_in_cache("048052", [ramo])

    monkeypatch.setattr(alberatura_mod, "comune_per_codice", _rifiuta_chiamata)
    monkeypatch.setattr(alberatura_mod, "fetch_guardato", _rifiuta_chiamata)
    monkeypatch.setattr("treasureiq.registro.leggi_registro", _rifiuta_chiamata)
    monkeypatch.setattr(alberatura_mod, "_rami_wp", _rifiuta_chiamata)
    monkeypatch.setattr(alberatura_mod, "_rami_html", _rifiuta_chiamata)

    rami = scopri_rami("048052")

    assert rami == [ramo]


def test_scopri_rami_json_corrotto_riscopre(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Predicato di gating (D-05, [[predicato-gating-cieco-a-nuovo-campo]]):
    `rami.json` illeggibile/campo mancante è cache assente, mai un crash —
    `scopri_rami` riscopre come se non ci fosse nulla su disco."""
    import treasureiq.alberatura as alberatura_mod

    comune_figline = ComuneNoto(
        codice_istat="048052", nome="Figline", provincia="FI", regione="Toscana", sito=BASE_FIGLINE
    )
    ramo_wp = RamoAT(etichetta="Bandi", url=f"{BASE_FIGLINE}/wp-json/wp/v2/amm-trasparente?x=1", tipo="concorso")

    monkeypatch.setattr(alberatura_mod, "CACHE_DIR", tmp_path)
    percorso = tmp_path / "048052" / "rami.json"
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text('{"verificato_il": "not-a-date"}', "utf-8")  # campo `rami` mancante

    monkeypatch.setattr(alberatura_mod, "comune_per_codice", lambda codice: comune_figline)
    monkeypatch.setattr(
        "treasureiq.registro.leggi_registro",
        lambda codice: SimpleNamespace(endpoints=SimpleNamespace(at=None)),
    )
    monkeypatch.setattr(alberatura_mod, "_rami_wp", lambda sonda, base: [ramo_wp])
    monkeypatch.setattr(alberatura_mod, "_rami_html", _rifiuta_chiamata)

    rami = scopri_rami("048052")

    assert rami == [ramo_wp]


def test_scopri_rami_esito_vuoto_non_si_cachea(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nessun ramo scoperto da nessun gradino -> `None`, e `rami.json` non
    viene mai scritto (stessa regola di `_in_cache`: mai un negativo su
    disco)."""
    import treasureiq.alberatura as alberatura_mod

    comune_figline = ComuneNoto(
        codice_istat="048052", nome="Figline", provincia="FI", regione="Toscana", sito=BASE_FIGLINE
    )

    monkeypatch.setattr(alberatura_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(alberatura_mod, "comune_per_codice", lambda codice: comune_figline)
    monkeypatch.setattr(
        "treasureiq.registro.leggi_registro",
        lambda codice: SimpleNamespace(endpoints=SimpleNamespace(at=None)),
    )
    monkeypatch.setattr(alberatura_mod, "_rami_wp", lambda sonda, base: None)
    monkeypatch.setattr(alberatura_mod, "_rami_html", lambda sonda, base: None)

    rami = scopri_rami("048052")

    assert rami is None
    assert not (tmp_path / "048052" / "rami.json").exists()
