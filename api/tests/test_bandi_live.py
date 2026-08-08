"""Test del motore live a due gradini `bandi_live` (KAPI 7, bandi-live-agid).

Fixture nello stile di `_SondaFinta`/`_RispostaFinta` (test_mappa_connettore.py
34,217): niente rete vera, niente Ollama vero — un `_SondaFinta.json(url)`
registra le rotte attese, e solleva se qualcuno chiede una rotta non prevista
(così un terzo tentativo non voluto si vede subito). `_ProviderFinto` implementa
il protocollo `LLMProvider` e, con `esplode=True`, fa fallire il test se il
motore chiama l'LLM quando non dovrebbe (prova di zero-LLM su cache calda).
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from treasureiq import bandi_live
from treasureiq.extract.llm import ExtractionResult
from treasureiq.sonda_live import ComuneNoto

BASE = "https://comune-test.example"
COMUNE_TEST = ComuneNoto(
    codice_istat="058003",
    nome="Comune di Prova",
    provincia="RM",
    regione="Lazio",
    sito="comune-test.example",
)


class _SondaFinta:
    """Doppio di `_Sonda`: stesso contratto (context manager + `.json(url)`),
    ma risponde solo alle rotte registrate — una rotta non registrata solleva,
    così un gradino/tentativo non previsto fa fallire il test invece di
    passare silenziosamente su un fallback."""

    def __init__(self, json_per_url: dict[str, object] | None = None) -> None:
        self._json = json_per_url or {}
        self._client = None
        self.richieste: list[str] = []

    def __enter__(self) -> "_SondaFinta":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def json(self, url: str) -> object:
        self.richieste.append(url)
        if url not in self._json:
            raise RuntimeError(f"rotta non finta: {url}")
        return self._json[url]


class _ProviderFinto:
    """Doppio di `LLMProvider`: `esplode=True` fa fallire il test se
    `.parse()` viene mai chiamato — la prova di zero-LLM sui casi TTL/cache."""

    name = "finto"

    def __init__(self, risultato: ExtractionResult | None = None, *, esplode: bool = False) -> None:
        self._risultato = risultato or ExtractionResult()
        self._esplode = esplode
        self.chiamate = 0

    @property
    def available(self) -> bool:
        return True

    def parse(self, *, system: str, user: str, output_model: object) -> ExtractionResult:
        self.chiamate += 1
        if self._esplode:
            raise AssertionError("provider finto chiamato: atteso zero-LLM in questo caso")
        return self._risultato


def _riga_bando(id_: int, titolo: str, corpo: str, *, con_pdf: bool = False, host_pdf: str = BASE) -> dict:
    corpo_html = f"<p>{corpo}</p>"
    if con_pdf:
        corpo_html += f'<a href="{host_pdf}/allegati/bando-{id_}.pdf">Allegato</a>'
    return {
        "id": id_,
        "title": {"rendered": titolo},
        "link": f"{BASE}/bandi/bando-{id_}/",
        "date": "2026-01-01T00:00:00",
        "excerpt": {"rendered": f"<p>{corpo[:80]}</p>"},
        "content": {"rendered": corpo_html},
    }


TESTO_CON_SEGNALE = (
    "Possono presentare domanda i cittadini residenti con ISEE inferiore a "
    "15.000 euro. Requisiti: residenza nel comune, nucleo familiare monogenitoriale."
)
TESTO_SENZA_SEGNALE = (
    "Il comune informa i cittadini che l'ufficio anagrafe osserva orario "
    "continuato dal lunedì al venerdì."
)

_URL_TASSONOMIE = f"{BASE}/wp-json/wp/v2/taxonomies"
_URL_CATEGORIE = f"{BASE}/wp-json/wp/v2/tipologie?per_page=100&_fields=id,name,count,slug"
_URL_CPT_BANDI = (
    f"{BASE}/wp-json/wp/v2/amm-trasparente?tipologie=7&per_page=20"
    "&_fields=title,link,date,excerpt,content&orderby=date&order=desc"
)

_JSON_TASSONOMIE_OK = {"tipologie": {"rest_base": "tipologie", "types": ["amm-trasparente"]}}
_JSON_CATEGORIE_OK = [{"id": 7, "name": "Criteri e modalità", "count": 2, "slug": "criteri-e-modalita"}]


def _url_pages(keyword: str) -> str:
    return f"{BASE}/wp-json/wp/v2/pages?search={quote(keyword)}&per_page=20"


@pytest.fixture(autouse=True)
def _isola_cache(tmp_path, monkeypatch):
    """Ogni test scrive sotto una CACHE_DIR privata: mai su `data-live/` vera."""
    monkeypatch.setattr(bandi_live, "CACHE_DIR", tmp_path / "bandi-criteri")


def _monkeypatch_sonda(monkeypatch, json_per_url: dict[str, object]) -> _SondaFinta:
    sonda = _SondaFinta(json_per_url)
    monkeypatch.setattr(bandi_live, "_Sonda", lambda timeout=10.0: sonda)
    return sonda


def _monkeypatch_provider(monkeypatch, provider: _ProviderFinto) -> None:
    monkeypatch.setattr(bandi_live, "load_provider", lambda role="extract": provider)


def _monkeypatch_comune(monkeypatch, comune: ComuneNoto | None) -> None:
    monkeypatch.setattr(bandi_live, "comune_per_codice", lambda codice: comune)


# --- 1. rung1 CPT vivo -------------------------------------------------------


def test_rung1_cpt_vivo_copre_con_bandi(monkeypatch):
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: _JSON_TASSONOMIE_OK,
            _URL_CATEGORIE: _JSON_CATEGORIE_OK,
            _URL_CPT_BANDI: [_riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)],
        },
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "cpt"
    assert len(esito.bandi) == 1
    assert esito.bandi[0].opportunity.title == "Bando contributi affitto"


# --- 2. rung1 miss -> rung2 hit ----------------------------------------------


def test_rung1_miss_rung2_hit_gradino_pages(monkeypatch):
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: {},  # nessuna tassonomia lega amm-trasparente: rung1 None
            _url_pages("bando"): [_riga_bando(11, "Bando ISEE", TESTO_CON_SEGNALE)],
        },
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "pages"
    assert len(esito.bandi) == 1


# --- 3. rung2 solo falsi positivi -> filtro segnale li scarta ----------------


def test_rung2_falsi_positivi_scartati_coperto_senza_bandi(monkeypatch):
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: {},
            _url_pages("bando"): [_riga_bando(21, "Orari ufficio anagrafe", TESTO_SENZA_SEGNALE)],
        },
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_senza_bandi"
    assert esito.gradino == "pages"
    assert esito.bandi == []


# --- 4. entrambi i gradini miss -> non_coperto, zero terzo tentativo --------


def test_entrambi_i_gradini_miss_non_coperto(monkeypatch):
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    sonda = _monkeypatch_sonda(monkeypatch, {_URL_TASSONOMIE: {}})
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "non_coperto"
    assert esito.gradino is None
    assert esito.bandi == []
    # Solo tassonomie + le 6 SEARCH_KEYWORDS: nessun terzo tentativo (niente
    # scraper Tier 3, niente rotta oltre le due previste dal contratto).
    assert sonda.richieste == [_URL_TASSONOMIE, *[_url_pages(k) for k in bandi_live.SEARCH_KEYWORDS]]


# --- 5. TTL hit (secondo giro): provider che esplode -> zero-LLM ------------


def test_ttl_hit_zero_rete_zero_llm(monkeypatch):
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: _JSON_TASSONOMIE_OK,
            _URL_CATEGORIE: _JSON_CATEGORIE_OK,
            _URL_CPT_BANDI: [_riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)],
        },
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    primo = bandi_live.bandi_arricchiti("058003", usa_cache=True)
    assert primo.esito == "coperto_con_bandi"

    # Secondo giro: sonda ESPLODE su qualunque rotta, provider ESPLODE se
    # chiamato. Se il motore va davvero in cache, nessuno dei due gira.
    def _sonda_esplosiva(timeout: float = 10.0) -> object:
        raise AssertionError("sonda istanziata: atteso zero-rete su cache calda")

    monkeypatch.setattr(bandi_live, "_Sonda", _sonda_esplosiva)
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))

    secondo = bandi_live.bandi_arricchiti("058003", usa_cache=True)

    assert secondo.esito == "coperto_con_bandi"
    assert secondo.verificato_il == primo.verificato_il


# --- 6. TTL scaduto + raw_hash invariato -> zero-LLM (cache estrazioni) -----


def test_ttl_scaduto_raw_hash_invariato_zero_llm(monkeypatch):
    from datetime import datetime, timedelta, timezone

    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    json_per_url = {
        _URL_TASSONOMIE: _JSON_TASSONOMIE_OK,
        _URL_CATEGORIE: _JSON_CATEGORIE_OK,
        _URL_CPT_BANDI: [_riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)],
    }
    _monkeypatch_sonda(monkeypatch, json_per_url)
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    primo = bandi_live.bandi_arricchiti("058003", usa_cache=True)
    assert primo.esito == "coperto_con_bandi"

    # Invecchia artificialmente il listing oltre il TTL, a contenuto REST
    # identico: stesso raw_hash, quindi la cache-estrazioni deve bastare.
    percorso_listing = bandi_live._percorso_listing("058003")
    vecchio = primo.model_copy(
        update={
            "verificato_il": (
                datetime.now(timezone.utc) - timedelta(hours=bandi_live.TTL_ORE + 1)
            ).isoformat()
        }
    )
    percorso_listing.write_text(vecchio.model_dump_json(indent=1), "utf-8")

    _monkeypatch_sonda(monkeypatch, json_per_url)  # stesso contenuto REST
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))  # deve restare inerte

    secondo = bandi_live.bandi_arricchiti("058003", usa_cache=True)

    assert secondo.esito == "coperto_con_bandi"
    assert len(secondo.bandi) == 1


# --- 7. cap prune -------------------------------------------------------------


def test_cap_prune_scarta_i_file_piu_vecchi(monkeypatch, tmp_path):
    monkeypatch.setattr(bandi_live, "CAP_CACHE_BYTES_PER_COMUNE", 100)
    root = bandi_live.CACHE_DIR / "058003" / "estrazioni"
    root.mkdir(parents=True)

    vecchio = root / "vecchio.v1.json"
    nuovo = root / "nuovo.v1.json"
    vecchio.write_text("x" * 80, "utf-8")
    nuovo.write_text("y" * 80, "utf-8")

    import os
    import time

    now = time.time()
    os.utime(vecchio, (now - 1000, now - 1000))
    os.utime(nuovo, (now, now))

    bandi_live._prune_cache("058003")

    assert not vecchio.exists()
    assert nuovo.exists()


# --- 8. guardia host PDF (anti-SSRF) -----------------------------------------


def test_guardia_host_pdf_scarta_url_esterno():
    tenuti, note = bandi_live._filtra_pdf_stesso_host(
        BASE,
        [
            f"{BASE}/allegati/bando.pdf",
            "https://altro-host.example/allegati/malevolo.pdf",
        ],
    )

    assert tenuti == [f"{BASE}/allegati/bando.pdf"]
    assert len(note) == 1
    assert "host esterno" in note[0]


def test_guardia_host_pdf_end_to_end_non_scarica_host_esterno(monkeypatch):
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    corpo_con_pdf_esterno = TESTO_CON_SEGNALE + (
        ' <a href="https://altro-host.example/malevolo.pdf">Allegato</a>'
    )
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: _JSON_TASSONOMIE_OK,
            _URL_CATEGORIE: _JSON_CATEGORIE_OK,
            _URL_CPT_BANDI: [_riga_bando(1, "Bando con allegato esterno", corpo_con_pdf_esterno)],
        },
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    nota_host = [n for n in esito.bandi[0].opportunity.extraction_notes if "host esterno" in n]
    assert len(nota_host) == 1
    assert esito.bandi[0].opportunity.pdfs_linked == 0


# --- 9. codice ignoto ---------------------------------------------------------


def test_codice_ignoto_comune_ignoto(monkeypatch):
    _monkeypatch_comune(monkeypatch, None)

    esito = bandi_live.bandi_arricchiti("999999", usa_cache=False)

    assert esito.esito == "comune_ignoto"
    assert esito.gradino is None
    assert esito.bandi == []
