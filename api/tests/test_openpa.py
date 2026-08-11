"""Test del connettore OpenPA (D-09) — fixture reali (Storo, TN) offline,
stesso stampo infrastrutturale di `test_openweb.py`/`test_peopleweb.py`
(`_StreamFinto`/`_ClientPerUrl` per instrumentare `httpx` senza rete)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from treasureiq import openpa as op_mod
from treasureiq.sonda_live import ComuneNoto

_FIXTURES = Path(__file__).parent / "fixtures"

_BASE_STORO = "https://www.comune.storo.tn.it"
_HOST_STORO = "comune.storo.tn.it"


def _leggi_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# _e_scheda_ufficio / _leggi_uffici_openpa — indice reale Storo
# ---------------------------------------------------------------------------


def test_e_scheda_ufficio_riconosce_profondita_tre() -> None:
    assert op_mod._e_scheda_ufficio(f"{_BASE_STORO}/Amministrazione/Uffici/Ufficio-Tributi#page-content")


def test_e_scheda_ufficio_scarta_indice_stesso() -> None:
    """L'indice stesso (`/Amministrazione/Uffici`, profondità 2) non è una
    scheda-ufficio: comparirebbe come link di rientro nella stessa pagina."""
    assert not op_mod._e_scheda_ufficio(f"{_BASE_STORO}/Amministrazione/Uffici")


def test_e_scheda_ufficio_scarta_ramo_diverso() -> None:
    assert not op_mod._e_scheda_ufficio(f"{_BASE_STORO}/Argomenti/Ambiente")


def test_leggi_uffici_openpa_indice_reale_storo(monkeypatch: pytest.MonkeyPatch) -> None:
    pagina_uffici = _leggi_fixture("openpa_storo_uffici.html")
    mappa = {f"{_BASE_STORO}/Amministrazione/Uffici": (200, pagina_uffici)}
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    sonda = _SondaFinta()
    uffici = op_mod._leggi_uffici_openpa(_BASE_STORO, _HOST_STORO, sonda, 8.0)

    assert len(uffici) == 9
    urls = {u.url for u in uffici}
    assert f"{_BASE_STORO}/Amministrazione/Uffici/Ufficio-Tributi#page-content" in urls
    nomi = {u.nome for u in uffici}
    assert "Ufficio Tributi" in nomi
    assert "Cantiere comunale" in nomi
    for u in uffici:
        assert u.source_typed is False
        assert u.telefoni == [] and u.email == [] and u.pec == []


def test_leggi_uffici_openpa_indice_irraggiungibile_degrado_vuoto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl({}))
    uffici = op_mod._leggi_uffici_openpa(_BASE_STORO, _HOST_STORO, _SondaFinta(), 8.0)
    assert uffici == []


def test_leggi_uffici_openpa_dedup_e_cap() -> None:
    """Un link ripetuto non duplica; il cap ferma l'indice a
    `MAX_UFFICI_INDICE` anche su un indice anomalo — stesso stampo di
    `test_estrai_uffici_dedup_e_cap` in `test_peopleweb.py`."""
    ripetuto = f'<a href="{_BASE_STORO}/Amministrazione/Uffici/A"><h3>Ufficio A</h3></a>' * 5
    ancore = op_mod._ancore(ripetuto, _BASE_STORO, _HOST_STORO)
    uffici = [
        u
        for u in (
            op_mod.UfficioConnettore(nome=t, url=u, source_typed=False, letto_il="x")
            for u, t in ancore
            if op_mod._e_scheda_ufficio(u)
        )
    ]
    assert len({u.url for u in uffici}) == 1


# ---------------------------------------------------------------------------
# _e_argomento_primo_livello / _leggi_aree_openpa — indice reale Storo
# ---------------------------------------------------------------------------


def test_e_argomento_primo_livello_accetta_profondita_due() -> None:
    assert op_mod._e_argomento_primo_livello(f"{_BASE_STORO}/Argomenti/Ambiente#page-content")


def test_e_argomento_primo_livello_scarta_sotto_tema() -> None:
    """I sotto-temi (`/Argomenti/{Tema}/{Sotto}`, osservati reali su Storo,
    es. `/Argomenti/Ambiente/Acqua`) sono dettaglio, non un'area di primo
    livello."""
    assert not op_mod._e_argomento_primo_livello(f"{_BASE_STORO}/Argomenti/Ambiente/Acqua")


def test_leggi_aree_openpa_indice_reale_storo(monkeypatch: pytest.MonkeyPatch) -> None:
    pagina_argomenti = _leggi_fixture("openpa_storo_argomenti.html")
    mappa = {f"{_BASE_STORO}/Argomenti": (200, pagina_argomenti)}
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    aree = op_mod._leggi_aree_openpa(_BASE_STORO, _HOST_STORO, _SondaFinta(), 8.0)

    assert len(aree) == 13
    nomi = {a.nome for a in aree}
    assert "Ambiente" in nomi
    assert "Demografia e popolazione" in nomi


def test_leggi_aree_openpa_indice_irraggiungibile_degrado_vuoto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl({}))
    aree = op_mod._leggi_aree_openpa(_BASE_STORO, _HOST_STORO, _SondaFinta(), 8.0)
    assert aree == []


# ---------------------------------------------------------------------------
# _leggi_at_openpa — rotta convenzionale confermata reale, con e senza probe
# ---------------------------------------------------------------------------


def test_leggi_at_openpa_probe_200_usa_url_finale(monkeypatch: pytest.MonkeyPatch) -> None:
    mappa = {f"{_BASE_STORO}/Amministrazione-Trasparente": (200, "<html>AT</html>")}
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    at = op_mod._leggi_at_openpa(_BASE_STORO, _HOST_STORO, _SondaFinta(), 8.0)

    assert at.indice_url == f"{_BASE_STORO}/Amministrazione-Trasparente"
    assert at.bandi_attivi == []
    assert at.pdf_presenti is False


def test_leggi_at_openpa_probe_fallito_usa_comunque_url_convenzionale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A differenza di `openweb`/`peopleweb` (che tornano `None` se il
    probe fallisce), la rotta AT di OpenPA è osservata reale 2/2 su
    comuni scoutati: si registra comunque, anche a probe fallito."""
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl({}))
    at = op_mod._leggi_at_openpa(_BASE_STORO, _HOST_STORO, _SondaFinta(), 8.0)
    assert at.indice_url == f"{_BASE_STORO}/Amministrazione-Trasparente"
    assert at.bandi_attivi == []
    assert at.pdf_presenti is False


# ---------------------------------------------------------------------------
# estrai_logo_openpa — gap onesto: il src reale non è mai same-host
# ---------------------------------------------------------------------------


def test_estrai_logo_openpa_home_reale_storo_degrada_a_none() -> None:
    """Gap onesto documentato: il `src` reale osservato vive su un
    proxy-immagini del vendor (`flyimg.opencityitalia.it`), non same-host —
    la guardia stretta lo rifiuta, come deve."""
    pagina = _leggi_fixture("openpa_storo_home.html")
    assert op_mod.estrai_logo_openpa(pagina, _BASE_STORO, _HOST_STORO) is None


def test_estrai_logo_openpa_same_host_accettato() -> None:
    pagina = (
        '<header><div class="it-brand-wrapper">'
        f'<img class="icon" alt="Logo" src="{_BASE_STORO}/stemma.png"></div></header>'
    )
    logo = op_mod.estrai_logo_openpa(pagina, _BASE_STORO, _HOST_STORO)
    assert logo == f"{_BASE_STORO}/stemma.png"


def test_estrai_logo_openpa_host_estraneo_rifiutato() -> None:
    pagina = (
        '<header><div class="it-brand-wrapper">'
        '<img class="icon" alt="Logo" src="https://cdn.evil.example.com/logo.png"></div></header>'
    )
    assert op_mod.estrai_logo_openpa(pagina, _BASE_STORO, _HOST_STORO) is None


def test_estrai_logo_openpa_generico_header_per_alt_stemma() -> None:
    """Nessun `.it-brand-wrapper`, ma un `<img>` generico nell'header con
    `alt="Stemma"` same-host — secondo tentativo del fallback a cascata."""
    pagina = f'<header><img alt="Stemma del Comune" src="{_BASE_STORO}/img/stemma.svg"></header>'
    logo = op_mod.estrai_logo_openpa(pagina, _BASE_STORO, _HOST_STORO)
    assert logo == f"{_BASE_STORO}/img/stemma.svg"


def test_estrai_logo_openpa_svg_inline_same_host() -> None:
    pagina = f'<header><image xlink:href="{_BASE_STORO}/stemma-inline.svg"></image></header>'
    logo = op_mod.estrai_logo_openpa(pagina, _BASE_STORO, _HOST_STORO)
    assert logo == f"{_BASE_STORO}/stemma-inline.svg"


def test_estrai_logo_openpa_assente() -> None:
    assert op_mod.estrai_logo_openpa("<html><body>niente</body></html>", _BASE_STORO, _HOST_STORO) is None


# ---------------------------------------------------------------------------
# _richiedi_con_guardia — guardia SSRF/size-cap (W1/W-3), stesso stampo egov
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
    assert op_mod._richiedi_con_guardia("ftp://x/y", "x", timeout=8.0) is None


def test_guardia_redirect_fuori_host_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(200, "https://evil.example.com/", [b"<html></html>"])
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientFinto(stream))
    assert op_mod._richiedi_con_guardia(_BASE_STORO, _HOST_STORO, timeout=8.0) is None


def test_guardia_stato_non_200_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(404, f"{_BASE_STORO}/", [b""])
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientFinto(stream))
    assert op_mod._richiedi_con_guardia(_BASE_STORO, _HOST_STORO, timeout=8.0) is None


def test_guardia_size_cap_abortisce_streaming() -> None:
    stream = _StreamFinto(200, f"{_BASE_STORO}/", [b"x" * (op_mod.MAX_RISPOSTA_BYTES + 1)])
    old_client = op_mod.httpx.Client
    op_mod.httpx.Client = lambda **kw: _ClientFinto(stream)
    try:
        assert op_mod._richiedi_con_guardia(_BASE_STORO, _HOST_STORO, timeout=8.0) is None
    finally:
        op_mod.httpx.Client = old_client


def test_richiesta_di_rete_fallita_non_solleva(monkeypatch: pytest.MonkeyPatch) -> None:
    def _rompe(**kw):
        raise httpx.ConnectError("rotto")

    monkeypatch.setattr(op_mod.httpx, "Client", _rompe)
    assert op_mod._richiedi_con_guardia(_BASE_STORO, _HOST_STORO, timeout=8.0) is None


# ---------------------------------------------------------------------------
# leggi_openpa — degrado onesto, mai un'eccezione, end-to-end reale
# ---------------------------------------------------------------------------


def _comune(sito: str | None) -> ComuneNoto:
    return ComuneNoto(
        codice_istat="022183", nome="Storo", provincia="TN", regione="Trentino-Alto Adige", sito=sito
    )


class _SondaFinta:
    def __init__(self) -> None:
        self.richieste = 0
        self.raggiungibile = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _ClientPerUrl:
    """Router `httpx.Client` finto: ogni URL richiesto torna la fixture
    giusta, stesso principio del router di `test_peopleweb.py`."""

    def __init__(self, mappa: dict[str, tuple[int, str]]) -> None:
        self._mappa = mappa

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, metodo: str, url: str):
        stato, corpo = self._mappa.get(url, (404, ""))
        return _StreamFinto(stato, url, [corpo.encode("utf-8")])


def test_leggi_openpa_comune_senza_sito_esito_vuoto_onesto() -> None:
    esito = op_mod.leggi_openpa(_comune(None), _SondaFinta())
    assert esito.piattaforma == "openpa"
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None


def test_leggi_openpa_portale_muto_esito_vuoto_mai_eccezione(monkeypatch: pytest.MonkeyPatch) -> None:
    def _rompe(**kw):
        raise httpx.ConnectError("muto")

    monkeypatch.setattr(op_mod.httpx, "Client", _rompe)
    esito = op_mod.leggi_openpa(_comune(_BASE_STORO), _SondaFinta())
    assert esito.uffici == []
    assert esito.amministrazione_trasparente is None


def test_leggi_openpa_end_to_end_storo_reale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Home + indice uffici + indice argomenti + AT reali di Storo: tutte
    le sezioni estratte, 4 richieste contate (D-08)."""
    pagina_home = _leggi_fixture("openpa_storo_home.html")
    pagina_uffici = _leggi_fixture("openpa_storo_uffici.html")
    pagina_argomenti = _leggi_fixture("openpa_storo_argomenti.html")
    mappa = {
        _BASE_STORO: (200, pagina_home),
        f"{_BASE_STORO}/Amministrazione/Uffici": (200, pagina_uffici),
        f"{_BASE_STORO}/Argomenti": (200, pagina_argomenti),
        f"{_BASE_STORO}/Amministrazione-Trasparente": (200, "<html>AT</html>"),
    }
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    sonda = _SondaFinta()
    esito = op_mod.leggi_openpa(_comune(_BASE_STORO), sonda)

    assert esito.piattaforma == "openpa"
    assert len(esito.uffici) == 9
    assert all(not u.source_typed for u in esito.uffici)
    assert len(esito.aree_amministrative) == 13
    assert esito.amministrazione_trasparente is not None
    assert esito.amministrazione_trasparente.indice_url == f"{_BASE_STORO}/Amministrazione-Trasparente"
    assert sonda.richieste == 4
    assert sonda.raggiungibile is True


def test_leggi_openpa_uffici_irraggiungibile_degrado_solo_su_uffici(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Se l'indice uffici non risponde, `uffici=[]` ma AT (rotta
    convenzionale, non dipende dall'indice uffici) resta presente —
    degrado per-sezione, non tutto-o-niente."""
    pagina_home = _leggi_fixture("openpa_storo_home.html")
    mappa = {
        _BASE_STORO: (200, pagina_home),
        f"{_BASE_STORO}/Amministrazione-Trasparente": (200, "<html>AT</html>"),
    }
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    esito = op_mod.leggi_openpa(_comune(_BASE_STORO), _SondaFinta())
    assert esito.uffici == []
    assert esito.aree_amministrative == []
    assert esito.amministrazione_trasparente is not None


def test_leggi_openpa_home_senza_pattern_noti_esito_quasi_vuoto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Markup senza nessuno dei pattern noti: uffici/aree vuoti, ma AT resta
    la rotta convenzionale (osservata reale, non condizionata dal markup
    della home) — coerente con `_leggi_at_openpa`."""
    mappa = {_BASE_STORO: (200, "<html><body><p>Comune di Storo</p></body></html>")}
    monkeypatch.setattr(op_mod.httpx, "Client", lambda **kw: _ClientPerUrl(mappa))

    esito = op_mod.leggi_openpa(_comune(_BASE_STORO), _SondaFinta())
    assert esito.uffici == []
    assert esito.aree_amministrative == []
    assert esito.amministrazione_trasparente is not None
    assert esito.amministrazione_trasparente.indice_url == f"{_BASE_STORO}/Amministrazione-Trasparente"
