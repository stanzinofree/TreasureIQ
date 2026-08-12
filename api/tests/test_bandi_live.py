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
from treasureiq.extract.llm import ExtractionResult, Segment
from treasureiq.mappa_connettore import MappaConnettore
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


@pytest.fixture(autouse=True)
def _alberatura_muta_di_default(monkeypatch):
    """Terzo gradino (KAPI 8): quando cpt/pages non producono bandi,
    `bandi_arricchiti` ORA prova sempre anche `alberatura` — con una sonda di
    rete propria. Di default nei test la si tiene muta (`None`, come un
    portale irraggiungibile) cosi' i test scritti per i primi due gradini
    restano deterministici e senza rete; chi vuole esercitare il terzo
    gradino lo rimonkeypatcha esplicitamente sull'oggetto `monkeypatch`."""
    monkeypatch.setattr(
        bandi_live.alberatura, "estrai_bandi", lambda codice, timeout=8.0: None
    )


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


# --- 1b. read-first: mappa-connettore calda (ciclo18a, D-01/D-05/D-06) ------
#
# Quando `mappa-connettore` per il comune e' gia' in cache, dice
# `amministrazione_trasparente_via == "REST"` e ha gia' il `rest_base` della
# tassonomia amm-trasparente, `_rung1_cpt` non deve rifare il probe
# `/wp-json/wp/v2/taxonomies` (`_rest_base_tassonomia_per_tipo`): il valore
# e' gia' stato misurato da `_sonda_mappa`.


def _mappa_cache(*, via: str, rest_base: str | None) -> MappaConnettore:
    return MappaConnettore(
        codice_istat="058003",
        nome="Comune Test",
        sito="comune-test.example",
        sondato_il="2026-08-01T00:00:00+00:00",
        amministrazione_trasparente_via=via,
        amministrazione_trasparente_rest_base=rest_base,
    )


def test_rung1_cpt_cache_calda_con_rest_base_salta_probe_tassonomie(monkeypatch):
    """(1) Cache calda + campo popolato: `_rest_base_tassonomia_per_tipo` non
    e' MAI chiamato (assert sul mock), e il gradino cpt risolve comunque."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    sonda = _monkeypatch_sonda(
        monkeypatch,
        {
            # NIENT'ALTRO che _URL_CATEGORIE/_URL_CPT_BANDI: se il codice
            # chiedesse comunque _URL_TASSONOMIE, _SondaFinta solleverebbe
            # "rotta assente" prima ancora dell'assert esplicito sotto.
            _URL_CATEGORIE: _JSON_CATEGORIE_OK,
            _URL_CPT_BANDI: [_riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)],
        },
    )

    def _esplode(*args, **kwargs):
        raise AssertionError("_rest_base_tassonomia_per_tipo chiamato: probe non evitato")

    monkeypatch.setattr(bandi_live, "_rest_base_tassonomia_per_tipo", _esplode)
    monkeypatch.setattr(
        bandi_live.mappa_connettore_module,
        "_da_cache",
        lambda codice: _mappa_cache(via="REST", rest_base="tipologie"),
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "cpt"
    assert len(esito.bandi) == 1
    assert _URL_TASSONOMIE not in sonda.richieste


def test_rung1_cpt_cache_calda_senza_rest_base_ripiega_su_probe(monkeypatch):
    """(2) Cache calda ma il campo e' ancora `None` (voce scritta prima di
    questo campo): valida-ma-incompleta, non un buco -> si degrada al probe
    live come prima di ciclo18a, comportamento identico a cache assente."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: _JSON_TASSONOMIE_OK,
            _URL_CATEGORIE: _JSON_CATEGORIE_OK,
            _URL_CPT_BANDI: [_riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)],
        },
    )
    monkeypatch.setattr(
        bandi_live.mappa_connettore_module,
        "_da_cache",
        lambda codice: _mappa_cache(via="REST", rest_base=None),
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "cpt"
    assert len(esito.bandi) == 1


def test_rung1_cpt_cache_assente_usa_probe_live(monkeypatch):
    """(3) Nessuna cache mappa-connettore (comune mai sondato): probe live
    come sempre, `codice_istat` passato non cambia l'esito."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: _JSON_TASSONOMIE_OK,
            _URL_CATEGORIE: _JSON_CATEGORIE_OK,
            _URL_CPT_BANDI: [_riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)],
        },
    )
    monkeypatch.setattr(
        bandi_live.mappa_connettore_module, "_da_cache", lambda codice: None
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "cpt"
    assert len(esito.bandi) == 1


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


# --- 4. cpt/pages miss -> terzo gradino (alberatura); tutti e tre miss -> non_coperto


def test_cpt_pages_miss_alberatura_muta_non_coperto(monkeypatch):
    """I due gradini REST (cpt/pages) non coprono, e il terzo (`alberatura`,
    KAPI 8) e' anch'esso muto (`None`): esito onesto `non_coperto`, non
    cristallizzato in cache (stesso principio del miss a due gradini)."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    sonda = _monkeypatch_sonda(monkeypatch, {_URL_TASSONOMIE: {}})
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))
    monkeypatch.setattr(
        bandi_live.alberatura, "estrai_bandi", lambda codice, timeout=8.0: None
    )

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "non_coperto"
    assert esito.gradino is None
    assert esito.bandi == []
    # Solo tassonomie + le 6 SEARCH_KEYWORDS sul gradino cpt/pages: nessun
    # terzo tentativo su QUELLA sonda (niente scraper Tier 3). Il terzo
    # gradino vero e proprio (`alberatura`) usa una sonda propria, mockata
    # sopra a livello di funzione — non transita da `sonda`.
    assert sonda.richieste == [_URL_TASSONOMIE, *[_url_pages(k) for k in bandi_live.SEARCH_KEYWORDS]]


def test_cpt_pages_miss_alberatura_copre_ordina_agevolazioni_prima(monkeypatch):
    """Terzo gradino: quando cpt/pages non coprono, `alberatura.estrai_bandi`
    diventa la fonte. A5: agevolazioni prima dei concorsi in un ordinamento
    stabile, `tipo` valorizzato da `BandoScoperto.tipo` su ogni bando."""
    from treasureiq.alberatura import BandoScoperto
    from treasureiq.mappa_connettore import Bando

    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_sonda(monkeypatch, {_URL_TASSONOMIE: {}})
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))

    scoperti = [
        BandoScoperto(
            bando=Bando(
                titolo="Concorso pubblico istruttore",
                url=f"{BASE}/zf/index.php/bandi-di-concorso/dettaglio/1",
                data="31/12/2026",
                anteprima=None,
            ),
            tipo="concorso",
            vendor="halley",
        ),
        BandoScoperto(
            bando=Bando(
                titolo="Contributo affitto",
                url=f"{BASE}/amministrazione-trasparente/contributo-affitto",
                data="",
                anteprima="Contributo per famiglie in difficolta' economica.",
            ),
            tipo="agevolazione",
            vendor="wp",
        ),
    ]
    monkeypatch.setattr(
        bandi_live.alberatura,
        "estrai_bandi",
        lambda codice, timeout=8.0: scoperti,
    )

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "alberatura"
    assert [b.tipo for b in esito.bandi] == ["agevolazione", "concorso"]
    concorso = esito.bandi[1]
    assert concorso.opportunity.title == "Concorso pubblico istruttore"
    # Concorso: scadenza copiata verbatim dalla colonna strutturale del
    # listing, mai passata dall'estrattore (D-06).
    assert concorso.scadenza == "31/12/2026"
    assert concorso.scadenza_verificata is True
    assert concorso.opportunity.requirements == bandi_live.Requirements()


def test_alberatura_senza_bandi_coperto_senza_bandi_cache(monkeypatch):
    """Rami trovati ma nessun bando estratto (`[]`, non `None`):
    `coperto_senza_bandi` con `gradino="alberatura"`, e la cache scrive
    l'esito (a differenza del `None`, che non e' mai cristallizzato)."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_sonda(monkeypatch, {_URL_TASSONOMIE: {}})
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))
    monkeypatch.setattr(
        bandi_live.alberatura, "estrai_bandi", lambda codice, timeout=8.0: []
    )

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_senza_bandi"
    assert esito.gradino == "alberatura"
    assert esito.bandi == []

    cached = bandi_live._da_cache("058003")
    assert cached is not None
    assert cached.gradino == "alberatura"


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


# --- 10. gate scadenza (D-07, consapevole del formato-data) -------------------


def _seg(testo: str) -> Segment:
    return Segment(kind="pagina", url="u", page_number=None, start=0, text=testo)


def test_scadenza_verificata_su_prosa_italiana():
    """La regressione che il gate risolveva sempre False: una data ISO è sotto
    la soglia fuzzy di `quote_appears_in`. Ora la verifica è consapevole del
    formato: la prosa `15 marzo 2026` conferma `2026-03-15`."""
    assert bandi_live._scadenza_nel_corpus(
        "2026-03-15", [_seg("Le domande vanno presentate entro il 15 marzo 2026.")]
    )


@pytest.mark.parametrize(
    "testo",
    ["scadenza 15/03/2026", "entro il 15-03-2026", "termine: 2026-03-15"],
)
def test_scadenza_verificata_su_forme_numeriche(testo):
    assert bandi_live._scadenza_nel_corpus("2026-03-15", [_seg(testo)])


def test_scadenza_non_verificata_se_data_assente():
    """Nessuna scadenza se la data non compare nel corpus letto (mai fiducia
    cieca nel modello: la data deve stare nella fonte)."""
    assert not bandi_live._scadenza_nel_corpus(
        "2026-03-15", [_seg("Il bando riguarda i residenti, senza una data.")]
    )


def test_scadenza_iso_malformata_non_esplode():
    assert not bandi_live._scadenza_nel_corpus("non-una-data", [_seg("15 marzo 2026")])


# --- 11. gate precisione `_ha_segnale` (WP search= è per sottostringa) --------
#
# Regressione «La Storia»: `search=bando` sul rung-2 fa match sottostringa e
# pesca «abbandono» in una pagina-museo su una moneta del IV secolo a.C. Il
# gate ora pretende un VERO termine-bando a confine di parola PRIMA del segnale
# di ammissibilità. Un falso qui è peggio di «nessun bando» (esito onesto).


def test_ha_segnale_rifiuta_sottostringa_abbandono():
    """«abbandono» contiene «bando» ma non è un termine-bando: va rifiutato
    anche se il testo ha parvenza di prosa amministrativa."""
    rec = _riga_bando(
        1,
        "La Storia",
        "Il museo custodisce una moneta del IV secolo a.C., a lungo in stato "
        "di abbandono, oggi restaurata. I residenti possono presentare "
        "richiesta di visita guidata.",
    )
    assert bandi_live._ha_segnale(rec) is False


def test_ha_segnale_rifiuta_segnale_senza_contesto_bando():
    """Un segnale di ammissibilità (ISEE/residenza) da solo non basta: senza
    un termine-bando resta una pagina di servizi, non un bando."""
    rec = _riga_bando(
        1,
        "Servizio mensa scolastica",
        "Le tariffe sono calcolate sull'ISEE del nucleo familiare residente "
        "nel comune. Possono presentare domanda i genitori degli iscritti.",
    )
    assert bandi_live._ha_segnale(rec) is False


def test_ha_segnale_accetta_bando_con_contesto_e_segnale():
    """Il caso vero: termine-bando nel titolo + segnale di ammissibilità nel
    corpo → estrazione dovuta."""
    rec = _riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)
    assert bandi_live._ha_segnale(rec) is True


def test_ha_segnale_accetta_contesto_nel_corpo_con_pdf():
    """Termine-bando nel CORPO (non nel titolo) + PDF collegato (dove lo spike
    ha trovato i criteri veri) → accettato anche senza segnale in prosa."""
    rec = _riga_bando(
        1,
        "Novità dal comune",
        "È aperto l'avviso pubblico per l'assegnazione dei voucher sport. "
        "Il modulo è nell'allegato.",
        con_pdf=True,
    )
    assert bandi_live._ha_segnale(rec) is True


# --- Documenti concorsi Halley /zf (estensione multi-piattaforma) -----------

_HALLEY_SCHEDA_HTML = """
<html><body>
  <a href="/zf/index.php/bandi-di-concorso/index/download-originali-bando/bando/94/originale/92"><i class="icon"></i></a>
  <a href="/zf/index.php/bandi-di-concorso/index/download-esito/bando/94/esito/57"></a>
  <a href="/zf/index.php/bandi-di-concorso/index/download-moduli-iscrizione/bando/94/modulo/3"></a>
  <a href="/altro/pagina">non un documento</a>
</body></html>
"""


def test_documenti_halley_estrae_link_download_con_etichetta_dal_verbo():
    """Link `/download-<verbo>/bando/N` → Documento con URL assoluto e
    etichetta derivata dal verbo dell'endpoint (fonte del portale, non un
    titolo inventato)."""
    base = "https://web.comune.esempio.it/zf/index.php/bandi-di-concorso/index/dettaglio/concorsi/in-corso/bando/94"
    docs = bandi_live._documenti_halley(base, _HALLEY_SCHEDA_HTML)
    etichette = {d.etichetta for d in docs}
    assert etichette == {"Documento del bando", "Esito della procedura", "Modulo di iscrizione"}
    assert all(d.url.startswith("https://web.comune.esempio.it/zf/") for d in docs)
    # La pagina generica non è un documento.
    assert all("/altro/pagina" not in d.url for d in docs)


def test_documenti_halley_dedup_e_cap():
    """Stesso URL due volte → una voce; oltre il cap non si aggiunge."""
    ripetuto = (
        '<a href="/zf/download-originali-bando/bando/1/originale/1"></a>'
        '<a href="/zf/download-originali-bando/bando/1/originale/1"></a>'
    )
    docs = bandi_live._documenti_halley("https://x.it/zf/dettaglio", ripetuto)
    assert len(docs) == 1


def test_etichetta_halley_prefisso_e_default():
    assert bandi_live._etichetta_halley("graduatoria-finale") == "Graduatoria"
    assert bandi_live._etichetta_halley("traccia-prova-orale") == "Traccia della prova"
    assert bandi_live._etichetta_halley("qualcosa-di-ignoto") == "Documento"


# --- Dispatch AT-aware (ciclo18a B3, D-01/D-03/D-05/D-06) --------------------
#
# `_CONNETTORE_AT_PER_PIATTAFORMA` restava vuoto per costruzione (B5,
# ciclo16): queste regressioni coprono `_GRADINI_PER_PIATTAFORMA_AT`, la
# tabella che ora sceglie quali gradini tentare in base a `piattaforma_at`
# letta dal registro.

from datetime import datetime, timedelta, timezone  # noqa: E402

from treasureiq.ingest.piattaforma import Piattaforma  # noqa: E402
from treasureiq.registro import EndpointsRegistro, RegistroComune  # noqa: E402


def _registro_finto(
    *, piattaforma_at: str | None, ultima_scansione: str | None
) -> RegistroComune:
    """Un record di registro minimo, solo coi campi che il dispatch legge.
    `ultima_scansione`, se `None`, replica un record scritto prima del campo
    (mai un TypeError sui test: il modello lo richiede str, quindi il test
    che vuole "assente" passa comunque una stringa lontana nel tempo — vedi
    `test_dispatch_piattaforma_at_assente_cascata_cieca`)."""
    return RegistroComune(
        codice_istat="058003",
        nome="Comune di Prova",
        dominio="comune-test.example",
        piattaforma="wordpress_generico",
        piattaforma_at=piattaforma_at,
        endpoints=EndpointsRegistro(),
        ultima_scansione=ultima_scansione or _ora_fresca(),
        prima_scansione=False,
    )


def _ora_fresca() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ora_scaduta() -> str:
    return (
        datetime.now(timezone.utc)
        - timedelta(days=bandi_live.TTL_CATALOGO_AT_GIORNI + 1)
    ).isoformat()


def _monkeypatch_registro(monkeypatch, record: RegistroComune | None) -> None:
    monkeypatch.setattr("treasureiq.registro.leggi_registro", lambda codice: record)


def test_dispatch_wp_amm_trasp_prova_cpt_pages_e_alberatura(monkeypatch):
    """(1) `wp_amm_trasp` catalogato e fresco: la voce di
    `_GRADINI_PER_PIATTAFORMA_AT` autorizza tutti e tre i gradini — cpt
    trova bandi, quindi alberatura non va MAI toccata (short-circuit
    invariato: il REST ha già risposto)."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_registro(
        monkeypatch,
        _registro_finto(
            piattaforma_at=Piattaforma.WP_AMM_TRASP.value, ultima_scansione=_ora_fresca()
        ),
    )
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: _JSON_TASSONOMIE_OK,
            _URL_CATEGORIE: _JSON_CATEGORIE_OK,
            _URL_CPT_BANDI: [_riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)],
        },
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    chiamate_alberatura: list[str] = []
    monkeypatch.setattr(
        bandi_live.alberatura,
        "estrai_bandi",
        lambda codice, timeout=8.0: chiamate_alberatura.append(codice) or None,
    )

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "cpt"
    assert len(esito.bandi) == 1
    assert esito.piattaforma_at == Piattaforma.WP_AMM_TRASP.value
    # cpt ha già risposto con bandi: alberatura resta non toccata, come
    # prima di questo brief (D-01: mai riverificare quello che è già coperto).
    assert chiamate_alberatura == []


def test_dispatch_halley_trasparenza_unione_pages_piu_alberatura(monkeypatch):
    """(2) BLOCKER: `halley_trasparenza` (Benevento-like, `via="scrape"`)
    DEVE tentare `pages` (mai solo `alberatura`): l'apice WP non risolve
    `cpt` ma risponde su `pages` a zero bandi, i concorsi veri arrivano da
    `alberatura` sul sottodominio Halley. Entrambe le fonti restano vive
    nella stessa chiamata."""
    from treasureiq.alberatura import BandoScoperto
    from treasureiq.mappa_connettore import Bando

    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_registro(
        monkeypatch,
        _registro_finto(
            piattaforma_at=Piattaforma.HALLEY_TRASPARENZA.value, ultima_scansione=_ora_fresca()
        ),
    )
    # cpt non risolve (tassonomia AT assente, `via="scrape"`); pages
    # risponde vivo ma senza candidati col segnale — coperto_senza_bandi.
    sonda = _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: {},
            **{_url_pages(k): [] for k in bandi_live.SEARCH_KEYWORDS},
        },
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))

    scoperti = [
        BandoScoperto(
            bando=Bando(
                titolo="Concorso pubblico istruttore",
                url=f"{BASE}/zf/index.php/bandi-di-concorso/dettaglio/1",
                data="31/12/2026",
                anteprima=None,
            ),
            tipo="concorso",
            vendor="halley",
        ),
    ]
    monkeypatch.setattr(
        bandi_live.alberatura, "estrai_bandi", lambda codice, timeout=8.0: scoperti
    )

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    # Prova che `pages` è stato davvero tentato (non saltato dal dispatch):
    # `_scopri_bandi` interroga tutte le `SEARCH_KEYWORDS` su `wp/v2/pages`.
    assert any("wp/v2/pages" in r for r in sonda.richieste)
    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "alberatura"
    assert [b.opportunity.title for b in esito.bandi] == ["Concorso pubblico istruttore"]
    assert esito.piattaforma_at == Piattaforma.HALLEY_TRASPARENZA.value


def test_dispatch_piattaforma_at_assente_cascata_cieca(monkeypatch):
    """(3) Nessun record di registro (comune mai scansionato per l'AT):
    `piattaforma_at` è `None` -> cascata cieca invariata, stesso esito di
    prima di questo brief."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_registro(monkeypatch, None)
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
    assert esito.piattaforma_at is None
    assert esito.connettore_at is None


def test_dispatch_gradini_catalogati_vuoti_ripiega_su_mancanti(monkeypatch):
    """(4) I gradini catalogati (sottoinsieme SINTETICO, iniettato via
    monkeypatch — nessuna voce reale di `_GRADINI_PER_PIATTAFORMA_AT` è oggi
    ridotta, D-03 BLOCKER) tornano a vuoto: la rete di sicurezza tenta il
    gradino mancante e lo trova. Prova che il fallback-su-vuoto è vivo, non
    solo dichiarato."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_registro(
        monkeypatch,
        _registro_finto(piattaforma_at="piattaforma_finta", ultima_scansione=_ora_fresca()),
    )
    # Solo "cpt" catalogato per questa piattaforma finta: `_scopri_bandi`
    # prova comunque anche "pages" al suo interno (D-03: la cascata interna
    # resta atomica), ma qui NESSUNO dei due copre affatto (tassonomia
    # assente, nessuna rotta pages finta -> `_SondaFinta` la tratta come
    # muta) -> il dispatch deve ripiegare su "alberatura", assente dalla
    # voce catalogata.
    monkeypatch.setattr(
        bandi_live, "_GRADINI_PER_PIATTAFORMA_AT", {"piattaforma_finta": ("cpt",)}
    )
    _monkeypatch_sonda(monkeypatch, {_URL_TASSONOMIE: {}})
    _monkeypatch_provider(monkeypatch, _ProviderFinto(esplode=True))
    monkeypatch.setattr(bandi_live.alberatura, "estrai_bandi", lambda codice, timeout=8.0: [])

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    # cpt/pages non coprono affatto -> la rete di sicurezza tenta
    # "alberatura" (assente dalla voce catalogata): rami letti, zero bandi
    # -> copertura confermata, non un `non_coperto` prematuro.
    assert esito.esito == "coperto_senza_bandi"
    assert esito.gradino == "alberatura"


def test_dispatch_catalogo_scaduto_cascata_cieca(monkeypatch):
    """(5) `piattaforma_at` catalogata ma `ultima_scansione` oltre
    `TTL_CATALOGO_AT_GIORNI`: il dispatch non si fida più del catalogo e
    ripiega sulla cascata cieca fin dall'inizio (stesso esito della
    cascata cieca, non solo lo stesso gradino)."""
    _monkeypatch_comune(monkeypatch, COMUNE_TEST)
    _monkeypatch_registro(
        monkeypatch,
        _registro_finto(
            piattaforma_at=Piattaforma.WP_AMM_TRASP.value, ultima_scansione=_ora_scaduta()
        ),
    )
    _monkeypatch_sonda(
        monkeypatch,
        {
            _URL_TASSONOMIE: _JSON_TASSONOMIE_OK,
            _URL_CATEGORIE: _JSON_CATEGORIE_OK,
            _URL_CPT_BANDI: [_riga_bando(1, "Bando contributi affitto", TESTO_CON_SEGNALE)],
        },
    )
    _monkeypatch_provider(monkeypatch, _ProviderFinto())

    assert bandi_live._catalogo_at_scaduto(_ora_scaduta())
    assert bandi_live._gradini_da_tentare(
        Piattaforma.WP_AMM_TRASP.value, _ora_scaduta()
    ) == bandi_live._TUTTI_I_GRADINI

    esito = bandi_live.bandi_arricchiti("058003", usa_cache=False)

    assert esito.esito == "coperto_con_bandi"
    assert esito.gradino == "cpt"
    assert esito.piattaforma_at == Piattaforma.WP_AMM_TRASP.value
