"""Test del connettore Municipium (B2) — niente rete: ogni fetch è servito
da una fixture HTML reale (Pomezia, catturata una volta) o costruita ad hoc
per i casi limite (host esterno, sitemap senza org_unit)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from treasureiq import municipium
from treasureiq.connettore import AmministrazioneTrasparente
from treasureiq.ingest.censimento import _Sonda
from treasureiq.sonda_live import ComuneNoto

FIXTURES = Path(__file__).parent / "fixtures" / "municipium"
BASE = "https://www.comune.pomezia.rm.it"


def _leggi_fixture(nome: str) -> str:
    return (FIXTURES / nome).read_text("utf-8")


class _RispostaFinta:
    """Sostituto minimale di `httpx.Response`: espone solo ciò che
    `municipium.py` legge (`status_code`, `text`, `content`, `url`)."""

    def __init__(self, testo: str, *, status_code: int = 200, url: str | None = None):
        self.status_code = status_code
        self.text = testo
        self.content = testo.encode("utf-8")
        self.url = httpx.URL(url or BASE)


def _comune_pomezia() -> ComuneNoto:
    return ComuneNoto(codice_istat="058085", nome="Pomezia", provincia="RM", regione="Lazio", sito=BASE)


def _sonda_instradata(mappa: dict[str, _RispostaFinta]) -> _Sonda:
    """Una `_Sonda` reale (per il tipo) con `.risposta` rimpiazzato da un
    router url->fixture — niente client HTTP toccato."""
    sonda = _Sonda(timeout=1.0)

    def _risposta(url: str) -> _RispostaFinta:
        if url not in mappa:
            raise AssertionError(f"URL non atteso nel test: {url}")
        return mappa[url]

    sonda.risposta = _risposta  # type: ignore[method-assign]
    return sonda


# ---------------------------------------------------------------------------
# Discovery (D-02)
# ---------------------------------------------------------------------------


def test_scopri_uffici_estrae_org_unit_dalla_sitemap_e_scarta_host_esterno():
    sitemap = _leggi_fixture("sitemap_pomezia.html")
    sonda = _sonda_instradata({f"{BASE}/it/sitemap": _RispostaFinta(sitemap)})

    org_unit, link_sitemap = municipium._scopri_uffici(_comune_pomezia(), sonda)

    assert len(org_unit) == 5
    assert all(link.startswith(BASE) for link in org_unit)
    assert not any("api.municipiumapp.it" in link for link in org_unit)
    assert f"{BASE}/it/organizational_unit/servizio-tributi-31081" in org_unit
    # link_sitemap è il contratto verso B3: TUTTI i link, non filtrati.
    assert len(link_sitemap) > len(org_unit)


def test_scopri_uffici_fallback_aree_amministrative_quando_sitemap_vuota():
    sitemap = _leggi_fixture("sitemap_senza_org_unit.html")
    aree = _leggi_fixture("aree_amministrative.html")
    sonda = _sonda_instradata(
        {
            f"{BASE}/it/sitemap": _RispostaFinta(sitemap),
            f"{BASE}/it/page/aree-amministrative": _RispostaFinta(aree),
        }
    )

    org_unit, _ = municipium._scopri_uffici(_comune_pomezia(), sonda)

    assert len(org_unit) == 3
    assert f"{BASE}/it/organizational_unit/servizi-demografici" in org_unit


def test_scopri_uffici_sitemap_irraggiungibile_e_esito_vuoto():
    sonda = _Sonda(timeout=1.0)

    def _rompi(url: str) -> _RispostaFinta:
        raise httpx.ConnectError("dns muto", request=httpx.Request("GET", url))

    sonda.risposta = _rompi  # type: ignore[method-assign]

    org_unit, link_sitemap = municipium._scopri_uffici(_comune_pomezia(), sonda)

    assert org_unit == []
    assert link_sitemap == []


# ---------------------------------------------------------------------------
# Lettura ufficio (D-05/D-07)
# ---------------------------------------------------------------------------


def test_leggi_ufficio_ricco_tel_email_pec_verbatim():
    url = f"{BASE}/it/organizational_unit/servizio-tributi-31081"
    pagina = _leggi_fixture("ufficio_tributi.html")
    sonda = _sonda_instradata({url: _RispostaFinta(pagina, url=url)})

    ufficio = municipium._leggi_ufficio(url, sonda, "comune.pomezia.rm.it")

    assert ufficio is not None
    assert ufficio.nome == "Servizio Tributi"
    assert ufficio.telefoni == ["06 83997842"]
    assert ufficio.email == ["ufficio.tributi@comune.pomezia.rm.it"]
    assert ufficio.pec == ["tributi@pec.comune.pomezia.rm.it"]
    assert ufficio.source_typed is True
    # Il centralino ente (JSON-LD "06 911461") NON è un recapito di questo
    # ufficio — D-05: mai il centralino spacciato per diretto.
    assert "06 911461" not in ufficio.telefoni


def test_leggi_ufficio_scarno_solo_centralino_niente_tel_inventato():
    url = f"{BASE}/it/organizational_unit/servizi-demografici"
    pagina = _leggi_fixture("ufficio_demografici.html")
    sonda = _sonda_instradata({url: _RispostaFinta(pagina, url=url)})

    ufficio = municipium._leggi_ufficio(url, sonda, "comune.pomezia.rm.it")

    assert ufficio is not None
    assert ufficio.telefoni == []
    assert ufficio.email == []
    assert ufficio.pec == ["protocollo@pec.comune.pomezia.rm.it"]


def test_leggi_ufficio_guardia_host_post_redirect_scarta_host_esterno():
    url = f"{BASE}/it/organizational_unit/dirottato"
    pagina = _leggi_fixture("ufficio_tributi.html")
    # Simula un redirect finito fuori dal dominio del comune: la pagina
    # sarebbe pure leggibile, ma l'host finale non è quello atteso (A5).
    sonda = _sonda_instradata({url: _RispostaFinta(pagina, url="https://api.municipiumapp.it/it/altro")})

    ufficio = municipium._leggi_ufficio(url, sonda, "comune.pomezia.rm.it")

    assert ufficio is None


def test_leggi_ufficio_status_non_200_scarta():
    url = f"{BASE}/it/organizational_unit/assente"
    sonda = _sonda_instradata({url: _RispostaFinta("<html></html>", status_code=404, url=url)})

    assert municipium._leggi_ufficio(url, sonda, "comune.pomezia.rm.it") is None


# ---------------------------------------------------------------------------
# Degrado onesto (D-02b) e end-to-end
# ---------------------------------------------------------------------------


def test_leggi_municipium_zero_uffici_e_esito_magro_onesto():
    sitemap = _leggi_fixture("sitemap_senza_org_unit.html")
    aree = _leggi_fixture("aree_amministrative.html")
    # Nessuna delle voci risolte dal fallback aree-amministrative viene poi
    # letta come ufficio: qui si vuole il ramo "0 uffici scoperti".
    sonda = _sonda_instradata(
        {
            f"{BASE}/it/sitemap": _RispostaFinta(sitemap),
            f"{BASE}/it/page/aree-amministrative": _RispostaFinta(aree),
            f"{BASE}/it/organizational_unit/affari-generali": _RispostaFinta(
                "<html></html>", status_code=404
            ),
            f"{BASE}/it/organizational_unit/segretario-generale": _RispostaFinta(
                "<html></html>", status_code=404
            ),
            f"{BASE}/it/organizational_unit/servizi-demografici": _RispostaFinta(
                "<html></html>", status_code=404
            ),
        }
    )

    esito = municipium.leggi_municipium(_comune_pomezia(), sonda)

    assert esito.uffici == []
    assert esito.codice_istat == "058085"
    assert esito.piattaforma == "municipium"
    # Segnale residuo onesto (D-02b): le aree trovate, non un vuoto muto.
    assert len(esito.aree_amministrative) == 3


def test_leggi_municipium_end_to_end_uffici_ricco_e_scarno():
    sitemap = _leggi_fixture("sitemap_pomezia.html")
    tributi_url = f"{BASE}/it/organizational_unit/servizio-tributi-31081"
    demografici_url = f"{BASE}/it/organizational_unit/servizi-demografici"
    altri = [
        f"{BASE}/it/organizational_unit/consiglio-comunale",
        f"{BASE}/it/organizational_unit/affari-generali",
        f"{BASE}/it/organizational_unit/ufficio-ambiente",
    ]
    mappa = {
        f"{BASE}/it/sitemap": _RispostaFinta(sitemap),
        tributi_url: _RispostaFinta(_leggi_fixture("ufficio_tributi.html"), url=tributi_url),
        demografici_url: _RispostaFinta(_leggi_fixture("ufficio_demografici.html"), url=demografici_url),
    }
    for url in altri:
        mappa[url] = _RispostaFinta("<html></html>", status_code=404, url=url)
    sonda = _sonda_instradata(mappa)

    esito = municipium.leggi_municipium(_comune_pomezia(), sonda)

    assert len(esito.uffici) == 2
    nomi = {u.nome for u in esito.uffici}
    assert nomi == {"Servizio Tributi", "Servizi Demografici"}
    tributi = next(u for u in esito.uffici if u.nome == "Servizio Tributi")
    assert tributi.telefoni == ["06 83997842"]
    # Nessun ufficio letto → AT deferred (B3 non importabile in questo run
    # di test): il campo resta None, mai una lista finta.
    assert esito.amministrazione_trasparente is None


def test_leggi_municipium_delega_at_a_b3_se_disponibile(monkeypatch: pytest.MonkeyPatch):
    sitemap = _leggi_fixture("sitemap_senza_org_unit.html")
    sonda = _sonda_instradata({f"{BASE}/it/sitemap": _RispostaFinta(sitemap)})

    esito_at = AmministrazioneTrasparente(indice_url=f"{BASE}/it/page/amministrazione-trasparente")

    class _ModuloAtFinto:
        @staticmethod
        def leggi_at(comune, sonda, link_sitemap):  # noqa: ANN001 — firma del contratto B3
            return esito_at

    import sys

    monkeypatch.setitem(sys.modules, "treasureiq.municipium_at", _ModuloAtFinto)

    esito = municipium.leggi_municipium(_comune_pomezia(), sonda)

    assert esito.amministrazione_trasparente == esito_at


def test_leggi_municipium_comune_senza_sito_esito_vuoto_non_crasha():
    comune = ComuneNoto(codice_istat="999999", nome="Fantasma", provincia="RM", regione="Lazio", sito="")
    sonda = _Sonda(timeout=1.0)

    esito = municipium.leggi_municipium(comune, sonda)

    assert esito.uffici == []
    assert esito.codice_istat == "999999"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_comune_non_riconosciuto_esce_con_errore(capsys: pytest.CaptureFixture[str]):
    codice = municipium.main(["999999999-non-esiste"])

    assert codice == 1
    assert "non riconosciuto" in capsys.readouterr().err
