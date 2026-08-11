"""Test del connettore Siscom PeopleWeb (D-09) — fixture reali (Airasca,
Andrate, Angrogna, TO) offline, stesso stampo infrastrutturale di
`test_egov.py` (`_StreamFinto`/`_ClientPerUrl` per instrumentare `httpx`
senza rete)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from treasureiq import peopleweb as pw_mod
from treasureiq.sonda_live import ComuneNoto

_FIXTURES = Path(__file__).parent / "fixtures"

_BASE_AIRASCA = "https://www.comune.airasca.to.it"
_BASE_ANDRATE = "https://www.comune.andrate.to.it"
_BASE_ANGROGNA = "https://www.comune.angrogna.to.it"
_HOST_AIRASCA = "comune.airasca.to.it"
_HOST_ANDRATE = "comune.andrate.to.it"
_HOST_ANGROGNA = "comune.angrogna.to.it"


def _leggi_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# _url_indice_uffici / _url_at — riconoscimento sui due template reali
# ---------------------------------------------------------------------------


def test_url_indice_uffici_template_a_percorso_airasca() -> None:
    """Airasca (template "a percorso"): l'indice uffici è `/amministrazione
    /uffici`, in chiaro nella home."""
    pagina = _leggi_fixture("peopleweb_airasca_home.html")
    ancore = pw_mod._ancore(pagina, _BASE_AIRASCA, _HOST_AIRASCA)
    assert pw_mod._url_indice_uffici(ancore) == f"{_BASE_AIRASCA}/amministrazione/uffici"


def test_url_indice_uffici_template_a_querystring_andrate() -> None:
    """Andrate (template "a querystring"): l'indice uffici è il link
    relativo `Uffici`, risolto sullo stesso host."""
    pagina = _leggi_fixture("peopleweb_andrate_home.html")
    ancore = pw_mod._ancore(pagina, _BASE_ANDRATE, _HOST_ANDRATE)
    assert pw_mod._url_indice_uffici(ancore) == f"{_BASE_ANDRATE}/Uffici"


def test_url_at_template_a_percorso_airasca_per_pattern_url() -> None:
    """Airasca: il link AT si riconosce per PATTERN URL
    (`amministrazione-trasparente` nel path), non per testo."""
    pagina = _leggi_fixture("peopleweb_airasca_home.html")
    ancore = pw_mod._ancore(pagina, _BASE_AIRASCA, _HOST_AIRASCA)
    assert pw_mod._url_at(ancore) == f"{_BASE_AIRASCA}/servizi/amministrazione-trasparente"


def test_url_at_template_a_querystring_andrate_per_testo_ancora() -> None:
    """Andrate: l'id di categoria (`8230`) NON è fisso — il link si trova
    per TESTO dell'ancora ("Trasparenza amministrativa"), come in eGov."""
    pagina = _leggi_fixture("peopleweb_andrate_home.html")
    ancore = pw_mod._ancore(pagina, _BASE_ANDRATE, _HOST_ANDRATE)
    assert pw_mod._url_at(ancore) == f"{_BASE_ANDRATE}/Dettaglioargomenti?IDCategoria=8230"


def test_url_at_template_a_querystring_angrogna_id_categoria_diverso() -> None:
    """Angrogna ha un id di categoria diverso da Andrate (`28100` vs
    `8230`): la ricerca per testo generalizza, un id fisso no."""
    pagina = _leggi_fixture("peopleweb_angrogna_home.html")
    ancore = pw_mod._ancore(pagina, _BASE_ANGROGNA, _HOST_ANGROGNA)
    assert pw_mod._url_at(ancore) == f"{_BASE_ANGROGNA}/Dettaglioargomenti?IDCategoria=28100"


# ---------------------------------------------------------------------------
# _estrai_uffici_peopleweb — sui due template reali
# ---------------------------------------------------------------------------


def test_estrai_uffici_template_a_percorso_airasca_reale() -> None:
    pagina_uffici = _leggi_fixture("peopleweb_airasca_uffici.html")
    ancore = pw_mod._ancore(pagina_uffici, _BASE_AIRASCA, _HOST_AIRASCA)
    uffici = pw_mod._estrai_uffici_peopleweb(ancore)
    assert len(uffici) >= 10
    urls = {u.url for u in uffici}
    assert f"{_BASE_AIRASCA}/amministrazione/ufficio/24/PROTOCOLLO" in urls
    for u in uffici:
        assert u.source_typed is False
        assert u.telefoni == [] and u.email == [] and u.pec == []
        assert u.nome.strip() == u.nome and u.nome  # niente icona/whitespace residuo


def test_estrai_uffici_template_a_querystring_andrate_reale() -> None:
    pagina_uffici = _leggi_fixture("peopleweb_andrate_uffici.html")
    ancore = pw_mod._ancore(pagina_uffici, _BASE_ANDRATE, _HOST_ANDRATE)
    uffici = pw_mod._estrai_uffici_peopleweb(ancore)
    assert len(uffici) >= 5
    urls = {u.url for u in uffici}
    assert f"{_BASE_ANDRATE}/Uffici?IDUfficio=21036" in urls
    nomi = {u.nome for u in uffici}
    assert "Ufficio tributi" in nomi


def test_estrai_uffici_dedup_e_cap() -> None:
    """Un link ripetuto non duplica; il cap ferma l'indice a
    `MAX_UFFICI_INDICE` anche su un indice anomalo."""
    ancore = [(f"{_BASE_AIRASCA}/amministrazione/ufficio/1/A", "Ufficio A")] * 5
    uffici = pw_mod._estrai_uffici_peopleweb(ancore)
    assert len(uffici) == 1

    tante = [
        (f"{_BASE_AIRASCA}/amministrazione/ufficio/{i}/U{i}", f"Ufficio {i}")
        for i in range(pw_mod.MAX_UFFICI_INDICE + 50)
    ]
    uffici_capped = pw_mod._estrai_uffici_peopleweb(tante)
    assert len(uffici_capped) == pw_mod.MAX_UFFICI_INDICE


def test_estrai_uffici_scarta_link_senza_pattern_dettaglio() -> None:
    """Un link generico (nav/footer, es. l'indice stesso `/amministrazione
    /uffici`) non è un ufficio: niente pattern `/ufficio/{id}` o
    `?IDUfficio=`, va scartato."""
    ancore = [
        (f"{_BASE_AIRASCA}/amministrazione/uffici", "Uffici"),
        (f"{_BASE_AIRASCA}/novita", "Novità"),
    ]
    assert pw_mod._estrai_uffici_peopleweb(ancore) == []


# ---------------------------------------------------------------------------
# estrai_logo_peopleweb — src reale, cross-host reject, assente
# ---------------------------------------------------------------------------


def test_estrai_logo_peopleweb_percorso_assoluto_airasca_reale() -> None:
    pagina = _leggi_fixture("peopleweb_airasca_home.html")
    logo = pw_mod.estrai_logo_peopleweb(pagina, _BASE_AIRASCA, _HOST_AIRASCA)
    assert logo == f"{_BASE_AIRASCA}/images/logo_tratto.png"


def test_estrai_logo_peopleweb_percorso_relativo_andrate_reale() -> None:
    pagina = _leggi_fixture("peopleweb_andrate_home.html")
    logo = pw_mod.estrai_logo_peopleweb(pagina, _BASE_ANDRATE, _HOST_ANDRATE)
    assert logo == f"{_BASE_ANDRATE}/portals/1826/Skins/skinXhtml/Images/stemma.webp"


def test_estrai_logo_peopleweb_host_estraneo_rifiutato() -> None:
    pagina = '<div class="it-brand-wrapper"><img src="https://cdn.evil.example.com/logo.png"></div>'
    assert pw_mod.estrai_logo_peopleweb(pagina, _BASE_AIRASCA, _HOST_AIRASCA) is None


def test_estrai_logo_peopleweb_assente() -> None:
    assert pw_mod.estrai_logo_peopleweb("<html><body>niente</body></html>", _BASE_AIRASCA, _HOST_AIRASCA) is None


# ---------------------------------------------------------------------------
# _richiedi_con_guardia — guardia SSRF/size-cap (W1/W-3), stesso stampo eGov
# ---------------------------------------------------------------------------


class _StreamFinto:
    def __init__(self, status_code: int, url: str, pezzi: list[bytes]) -> None:
        self.status_code = status_code
        self.url = url
        self._pezzi = pezzi

    def iter_bytes(self):
        yield from self._pezzi

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _ClientFinto:
    def __init__(self, stream: _StreamFinto) -> None:
        self._stream = stream

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, metodo: str, url: str):
        return self._stream


def test_guardia_schema_non_http_rifiutato() -> None:
    assert pw_mod._richiedi_con_guardia("ftp://x/y", "x", timeout=8.0) is None


def test_guardia_redirect_fuori_host_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(200, "https://evil.example.com/", [b"<html></html>"])
    monkeypatch.setattr(pw_mod.httpx, "Client", lambda **kw: _ClientFinto(stream))
    assert pw_mod._richiedi_con_guardia("https://www.comune.airasca.to.it/", _HOST_AIRASCA, timeout=8.0) is None


def test_guardia_stato_non_200_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, "https://www.comune.airasca.to.it/", [b""])
    monkeypatch.setattr(pw_mod.httpx, "Client", lambda **kw: _ClientFinto(stream))
    assert pw_mod._richiedi_con_guardia("https://www.comune.airasca.to.it/", _HOST_AIRASCA, timeout=8.0) is None


def test_guardia_size_cap_abortisce_streaming() -> None:
    stream = _StreamFinto(
        200, "https://www.comune.airasca.to.it/", [b"x" * (pw_mod.MAX_RISPOSTA_BYTES + 1)]
    )

    class _ClientOversize(_ClientFinto):
        pass

    import treasureiq.peopleweb as mod

    old_client = mod.httpx.Client
    mod.httpx.Client = lambda **kw: _ClientOversize(stream)
    try:
        assert mod._richiedi_con_guardia("https://www.comune.airasca.to.it/", _HOST_AIRASCA, timeout=8.0) is None
    finally:
        mod.httpx.Client = old_client


def test_guardia_200_ok_ritorna_testo_e_url_finale(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(200, "https://www.comune.airasca.to.it/", [b"<html>ok</html>"])
    monkeypatch.setattr(pw_mod.httpx, "Client", lambda **kw: _ClientFinto(stream))
    esito = pw_mod._richiedi_con_guardia("https://www.comune.airasca.to.it/", _HOST_AIRASCA, timeout=8.0)
    assert esito == ("<html>ok</html>", "https://www.comune.airasca.to.it/")


def test_richiesta_di_rete_fallita_non_solleva(monkeypatch: pytest.MonkeyPatch) -> None:
    def _rompe(**kw):
        raise httpx.ConnectError("rotto")

    monkeypatch.setattr(pw_mod.httpx, "Client", _rompe)
    assert pw_mod._richiedi_con_guardia("https://www.comune.airasca.to.it/", _HOST_AIRASCA, timeout=8.0) is None


# ---------------------------------------------------------------------------
# leggi_peopleweb — degrado onesto, mai un'eccezione
# ---------------------------------------------------------------------------


def _comune(sito: str | None) -> ComuneNoto:
    return ComuneNoto(
        codice_istat="001008", nome="Airasca", provincia="TO", regione="Piemonte", sito=sito
    )


class _SondaFinta:
    def __init__(self) -> None:
        self.richieste = 0
        self.raggiungibile = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_leggi_peopleweb_comune_senza_sito_esito_vuoto_onesto() -> None:
    esito = pw_mod.leggi_peopleweb(_comune(None), _SondaFinta())
    assert esito.piattaforma == "peopleweb"
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None


def test_leggi_peopleweb_portale_muto_esito_vuoto_mai_eccezione(monkeypatch: pytest.MonkeyPatch) -> None:
    def _rompe(**kw):
        raise httpx.ConnectError("muto")

    monkeypatch.setattr(pw_mod.httpx, "Client", _rompe)
    esito = pw_mod.leggi_peopleweb(_comune("https://www.comune.airasca.to.it"), _SondaFinta())
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None


class _ClientPerUrl:
    """Router `httpx.Client` finto: ogni URL richiesto torna la fixture
    giusta, stesso principio del router di `test_egov.py`."""

    def __init__(self, mappa: dict[str, tuple[int, str]]) -> None:
        self._mappa = mappa

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, metodo: str, url: str):
        stato, corpo = self._mappa.get(url, (404, ""))
        return _StreamFinto(stato, url, [corpo.encode("utf-8")])


def test_leggi_peopleweb_end_to_end_airasca_reale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Home + indice uffici reali di Airasca: uffici index-only estratti,
    AT riconosciuta per pattern URL, 2 richieste contate (D-08)."""
    pagina_home = _leggi_fixture("peopleweb_airasca_home.html")
    pagina_uffici = _leggi_fixture("peopleweb_airasca_uffici.html")
    mappa = {
        _BASE_AIRASCA: (200, pagina_home),
        f"{_BASE_AIRASCA}/amministrazione/uffici": (200, pagina_uffici),
    }
    monkeypatch.setattr(pw_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    sonda = _SondaFinta()
    esito = pw_mod.leggi_peopleweb(_comune(_BASE_AIRASCA), sonda)

    assert esito.piattaforma == "peopleweb"
    assert len(esito.uffici) >= 10
    assert all(not u.source_typed for u in esito.uffici)
    assert esito.amministrazione_trasparente is not None
    assert esito.amministrazione_trasparente.indice_url == f"{_BASE_AIRASCA}/servizi/amministrazione-trasparente"
    assert esito.amministrazione_trasparente.bandi_attivi == []
    assert sonda.richieste == 2
    assert sonda.raggiungibile is True


def test_leggi_peopleweb_indice_uffici_irraggiungibile_degrado_solo_su_uffici(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Se l'indice uffici non risponde, `uffici=[]` ma AT (già nota dalla
    home) resta presente — degrado per-sezione, non tutto-o-niente."""
    pagina_home = _leggi_fixture("peopleweb_airasca_home.html")
    mappa = {_BASE_AIRASCA: (200, pagina_home)}
    monkeypatch.setattr(pw_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    esito = pw_mod.leggi_peopleweb(_comune(_BASE_AIRASCA), _SondaFinta())
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is not None


def test_leggi_peopleweb_home_senza_pattern_noti_esito_vuoto_onesto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Markup senza nessuno dei pattern noti: nessuna sezione riconosciuta,
    esito onesto (non fabbricato)."""
    mappa = {_BASE_AIRASCA: (200, "<html><body><p>Comune di Airasca</p></body></html>")}
    monkeypatch.setattr(pw_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    esito = pw_mod.leggi_peopleweb(_comune(_BASE_AIRASCA), _SondaFinta())
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None
    assert esito.aree_amministrative == []
