"""Il gradino 3 di D-32/D-58: cercare sul web quando il portale non basta.

Nessuna rete qui dentro. La sonda e il motore di ricerca sono sostituiti,
perché quello che va tenuto fermo non è cosa risponde oggi Brave — che
cambia domani — ma il patto che la risposta stringe con il cittadino:

* si cerca SOLO dopo che il portale ha risposto e non si è lasciato leggere;
* quello che torna non è mai un nostro dato, e la scheda lo dice per iscritto;
* un motore giù, o senza chiave, è una risposta in meno, mai una domanda
  fallita (D-59);
* prima si cerca sul sito del comune stesso (`site:`), poi ovunque (D-58);
* coperti e non coperti salgono la STESSA scala (B3b): la sonda gira sempre,
  la cache è solo un hint datato (D-60).

Il caso vero da cui nascono è Ciampino (058118): portale raggiungibile, uffici
non esposti in una forma leggibile, e una pagina URP che un motore trova al
primo colpo.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from treasureiq.chat import respond
from treasureiq.chat.intent import ChatIntent, QuestionKind, Topic
from treasureiq.ingest import websearch
from treasureiq.ingest.censimento import Indirizzabilita, RecuperabilitaOrari
from treasureiq.ingest.websearch import WebResult, WebSearchCacheEntry
from treasureiq.integration import AccessMode, Ente, Probe
from treasureiq.sonda_live import ComuneNoto, OrariLive

CIAMPINO = ComuneNoto(
    codice_istat="058118",
    nome="Ciampino",
    provincia="RM",
    regione="Lazio",
    sito="www.comune.ciampino.roma.it",
)

#: Il portale risponde ma non espone gli uffici: è esattamente il punto in cui
#: la chat si fermava, dicendo al cittadino di cercare a mano.
SOLO_HTML = OrariLive(
    codice_istat=CIAMPINO.codice_istat,
    nome=CIAMPINO.nome,
    sito="https://www.comune.ciampino.roma.it",
    indirizzabilita=Indirizzabilita.SOLO_HTML,
    recuperabilita=RecuperabilitaOrari.NON_TENTATO,
    letto_il="2026-08-04T00:00:00+00:00",
)

PAGINE = [
    respond.WebResultAnswer(
        title="URP - Città di Ciampino",
        url="https://www.comune.ciampino.roma.it/it/unita_organizzative/urp",
    ),
    respond.WebResultAnswer(
        title="Servizi demografici, elettorale - Città di Ciampino",
        url="https://www.comune.ciampino.roma.it/it/unita_organizzative/servizi-demografici",
    ),
]


@pytest.fixture
def portale_muto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comune riconosciuto, portale che risponde e non si lascia leggere."""
    monkeypatch.setattr(respond, "risolvi_comune", lambda _hint: CIAMPINO)
    monkeypatch.setattr(respond, "comune_per_codice", lambda _codice: CIAMPINO)
    monkeypatch.setattr(respond, "leggi_orari_urp", lambda _comune: SOLO_HTML)
    # B4: `_risposta_live` ora interroga `connettore.leggi_connettore` prima
    # del gradino web (D-06/A7: assente -> flusso invariato). Senza questo
    # patch il test farebbe una vera chiamata di rete verso Ciampino.
    monkeypatch.setattr(respond.connettore, "leggi_connettore", lambda *_a, **_k: None)


def _chiedi(*, parole: str = "", topic: Topic = Topic.ANAGRAFE_CARTA_IDENTITA):
    return asyncio.run(
        respond._risposta_live(
            hint="Ciampino",
            topic=topic,
            comune_istat=CIAMPINO.codice_istat,
            parole=parole,
        )
    )


def test_pagine_trovate_arrivano_al_cittadino(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: (list(PAGINE), None))

    risposta = _chiedi(parole="mi dici i numeri dell'ufficio anagrafe?")

    assert risposta is not None
    assert risposta.access_mode == AccessMode.M6_WEB_APERTO.value
    assert [r.url for r in risposta.info.web_results] == [r.url for r in PAGINE]


def test_la_provenienza_resta_scritta_nella_scheda(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il punto dell'intera funzione: trovato non è letto, e si deve vedere."""
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: (list(PAGINE), None))

    info = _chiedi(parole="orari dell'ufficio anagrafe").info

    testi = " ".join(p.testo.lower() for p in info.prove)
    assert "ricerca sul web" in testi
    assert "urp" in testi and "confermate" in testi
    # `letto_dal_vivo` significa «letto dal portale del comune». Qui non è
    # successo, e un bollo sbagliato varrebbe più di dieci righe giuste.
    assert info.letto_dal_vivo is False
    assert info.stato is respond.StatoFonte.NON_VERIFICATO
    assert info.document is None
    # Il rail INFORMAZIONE non produce verdetti, nemmeno passando di qui.
    assert risposta_senza_verdetto(info)


def risposta_senza_verdetto(info: respond.InfoAnswer) -> bool:
    return info.coverage_count == 0 and not hasattr(info, "verdict")


def test_senza_chiave_brave_alza_websearch_non_configurato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-59: niente chiave, niente motore — mai un secondo engine, mai una
    lista vuota che si spaccia per "cercato e trovato niente"."""
    monkeypatch.delenv(websearch.BRAVE_KEY_ENV, raising=False)

    with pytest.raises(websearch.WebSearchNonConfigurato):
        websearch.search_web("orari anagrafe comune di Ciampino")


def test_con_chiave_brave_va_a_search_brave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(websearch.BRAVE_KEY_ENV, "una-chiave-di-prova")
    chiamate: list[str] = []

    def finto_brave(query: str, *, api_key: str, timeout: float = 15.0) -> list[websearch.WebResult]:
        chiamate.append(query)
        return [websearch.WebResult(title="URP", url="https://www.comune.ciampino.roma.it/urp")]

    monkeypatch.setattr(websearch, "search_brave", finto_brave)

    risultati, provider = websearch.search_web("orari anagrafe comune di Ciampino")

    assert provider == "brave"
    assert chiamate == ["orari anagrafe comune di Ciampino"]
    assert [r.url for r in risultati] == ["https://www.comune.ciampino.roma.it/urp"]


def test_entro_ttl_a_sei_giorni_e_vero() -> None:
    entry = websearch.WebSearchCacheEntry(
        query="orari anagrafe",
        provider="brave",
        fetched_at=datetime.now(timezone.utc) - timedelta(days=6),
        results=[],
    )
    assert websearch.entro_ttl(entry, datetime.now(timezone.utc)) is True


def test_entro_ttl_a_otto_giorni_e_falso() -> None:
    entry = websearch.WebSearchCacheEntry(
        query="orari anagrafe",
        provider="brave",
        fetched_at=datetime.now(timezone.utc) - timedelta(days=8),
        results=[],
    )
    assert websearch.entro_ttl(entry, datetime.now(timezone.utc)) is False


def test_niente_dal_motore_non_diventa_niente_al_mondo(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-15: zero risultati non è una misura, è un'assenza di misura.

    Si torna alla risposta precedente — «il portale non si lascia leggere» —
    che è vera, invece di dichiarare che su quell'argomento non esiste nulla.
    """
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: ([], None))

    risposta = _chiedi(parole="orari dell'ufficio anagrafe")

    assert risposta.access_mode == AccessMode.M4_CONNETTORE.value
    assert risposta.info.web_results == []


def test_un_motore_giu_non_fa_fallire_la_domanda(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def esplode(_query: str) -> list[respond.WebResultAnswer]:
        raise RuntimeError("brave irraggiungibile")

    monkeypatch.setattr(respond, "search_web", lambda *a, **k: esplode(""))

    risposta = _chiedi(parole="orari dell'ufficio anagrafe")

    assert risposta is not None
    assert risposta.access_mode == AccessMode.M4_CONNETTORE.value


def test_senza_chiave_brave_risposta_onesta_senza_eccezione(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-59: nessuna chiave configurata non deve mai propagarsi come
    un'eccezione al cittadino — e il motivo va scritto, non solo loggato."""

    def niente_chiave(*_a, **_k):
        raise websearch.WebSearchNonConfigurato("BRAVE_SEARCH_API_KEY non impostata")

    monkeypatch.setattr(respond, "search_web", niente_chiave)

    risposta = _chiedi(parole="orari dell'ufficio anagrafe")

    assert risposta is not None
    assert risposta.access_mode == AccessMode.M4_CONNETTORE.value
    assert risposta.info.web_results == []
    assert any("non è disponibile" in riga for riga in risposta.info.diagnosis)


def test_la_query_scoped_al_sito_precede_quella_generica(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-58: prima `site:<host del comune>`, poi la query generica — mai il
    contrario. La query scoped che nomina l'ufficio vince già al primo passo."""
    viste: list[str] = []

    def registra(query: str) -> tuple[list[respond.WebResultAnswer], str | None]:
        viste.append(query)
        return list(PAGINE), None

    monkeypatch.setattr(respond, "_cerca_sul_web", registra)

    _chiedi(parole="mi dici i numeri dell'ufficio anagrafe?")

    assert viste == [
        "site:www.comune.ciampino.roma.it ufficio anagrafe comune di Ciampino contatti orari"
    ]


def test_query_generica_arriva_solo_se_lo_scoping_non_trova_nulla(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordine 3a -> 3b: il passo scoped con zero risultati fa scattare quello
    generico, e non il contrario."""
    viste: list[str] = []

    def registra(query: str) -> tuple[list[respond.WebResultAnswer], str | None]:
        viste.append(query)
        if query.startswith("site:"):
            return [], None
        return list(PAGINE), None

    monkeypatch.setattr(respond, "_cerca_sul_web", registra)

    risposta = _chiedi(parole="a chi posso chiedere?", topic=Topic.SCONOSCIUTO)

    assert viste == [
        "site:www.comune.ciampino.roma.it URP ufficio relazioni con il pubblico comune di Ciampino",
        "URP ufficio relazioni con il pubblico comune di Ciampino",
    ]
    assert risposta.access_mode == AccessMode.M6_WEB_APERTO.value


# ---------------------------------------------------------------------------
# B3b: la stessa scala anche per un ente già censito (D-58/D-60).
# ---------------------------------------------------------------------------

CIAMPINO_ENTE = Ente(
    ente="Comune di Ciampino",
    codice_istat=CIAMPINO.codice_istat,
    access_mode=AccessMode.M4_CONNETTORE,
    probe=Probe(method="html", dated=date(2026, 1, 1), dettagli={}),
    urp=None,
)


@pytest.fixture
def ente_coperto_ma_esaurito(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un ente CHE ABBIAMO censito (`load_enti`), ma senza dati istituzionali
    su questo argomento (M4_connettore): il caso che il vecchio bypass
    trattava con la sola cache, mai con la sonda."""
    monkeypatch.setattr(respond, "_resolve_informazione_ente", lambda *, hint: CIAMPINO_ENTE)
    monkeypatch.setattr(respond, "comune_per_codice", lambda _codice: CIAMPINO)
    # B4: `_build_informazione_answer` ora interroga `connettore.leggi_connettore`
    # prima del ramo institutional_exhausted quando access_mode e M4_CONNETTORE.
    # Assente -> flusso invariato (D-06/A7); senza patch sarebbe rete vera.
    monkeypatch.setattr(respond.connettore, "leggi_connettore", lambda *_a, **_k: None)


def _chiedi_informazione(*, monkeypatch: pytest.MonkeyPatch):
    intent = ChatIntent(
        topic=Topic.ANAGRAFE_CARTA_IDENTITA,
        kind=QuestionKind.INFORMAZIONE,
        comune_hint="Ciampino",
    )
    return asyncio.run(
        respond._build_informazione_answer(intent=intent, records=[], comune_istat=CIAMPINO.codice_istat)
    )


def test_ente_coperto_la_sonda_gira_comunque(
    ente_coperto_ma_esaurito: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-60: un orario cambiato ieri non aspetta il prossimo rigen. La sonda
    gira SEMPRE, anche per un ente che `enti.json` conosce già."""
    chiamate: list[str] = []
    monkeypatch.setattr(
        respond, "leggi_orari_urp", lambda comune: (chiamate.append(comune.nome), SOLO_HTML)[1]
    )
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: ([], None))
    monkeypatch.setattr(respond, "_websearch_query", lambda *, topic, ente: None)

    _chiedi_informazione(monkeypatch=monkeypatch)

    assert chiamate == ["Ciampino"]


def test_drill_ufficio_propaga_batch_al_chatanswer(
    ente_coperto_ma_esaurito: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il drill di un ufficio nominato produce anche gli artefatti v1
    (DataBatch/QueryPlan). Devono arrivare al `ChatAnswer` finale ANCHE quando
    il ramo connettore non intercetta la risposta (qui `leggi_connettore`
    torna None; stesso sink del ramo `candidates` non vuoto): prima il
    chiamante teneva solo `.office` e il batch già proiettato andava perso."""
    batch = object()
    plan = object()
    selected = object()

    monkeypatch.setattr(respond, "_ufficio_chiesto", lambda _parole: "anagrafe")

    async def _drill(**_kwargs):
        return respond.UfficioDrillResult(
            office=respond.OfficeAnswer(
                nome="Anagrafe", telefono=None, email=None,
                orari="Lun 9-12", orari_fonte=None,
            ),
            data_batches=[batch],
            query_plan=plan,
            selected_data_batch=selected,
        )

    monkeypatch.setattr(respond, "_office_da_ufficio_nominato", _drill)
    monkeypatch.setattr(respond, "leggi_orari_urp", lambda comune: SOLO_HTML)
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: ([], None))
    monkeypatch.setattr(respond, "_websearch_query", lambda *, topic, ente: None)

    risposta = _chiedi_informazione(monkeypatch=monkeypatch)

    assert risposta.data_batches == [batch]
    assert risposta.query_plan is plan
    assert risposta.selected_data_batch is selected


def test_cache_entro_ttl_diventa_hint_datato(
    ente_coperto_ma_esaurito: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(respond, "leggi_orari_urp", lambda _comune: SOLO_HTML)
    monkeypatch.setattr(respond, "_websearch_query", lambda *, topic, ente: "urp comune di Ciampino")
    fetched_at = datetime.now(timezone.utc) - timedelta(days=2)
    entry = WebSearchCacheEntry(
        query="urp comune di Ciampino",
        provider="brave",
        fetched_at=fetched_at,
        results=[WebResult(title=p.title, url=p.url) for p in PAGINE],
    )
    monkeypatch.setattr(respond, "load_websearch", lambda _query: entry)

    def fallisce_se_chiamata(*_a, **_k):
        raise AssertionError("la ricerca fresca non doveva partire: la cache era entro TTL")

    monkeypatch.setattr(respond, "_ricerca_a_gradini", fallisce_se_chiamata)

    risposta = _chiedi_informazione(monkeypatch=monkeypatch)

    assert [r.url for r in risposta.info.web_results] == [r.url for r in PAGINE]
    assert risposta.access_mode == AccessMode.M6_WEB_APERTO.value
    timbro = fetched_at.strftime("%d/%m/%Y")
    assert any(timbro in riga for riga in risposta.info.diagnosis)


def test_cache_oltre_ttl_si_ignora_e_si_cerca_di_nuovo(
    ente_coperto_ma_esaurito: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(respond, "leggi_orari_urp", lambda _comune: SOLO_HTML)
    monkeypatch.setattr(respond, "_websearch_query", lambda *, topic, ente: "urp comune di Ciampino")
    entry_scaduta = WebSearchCacheEntry(
        query="urp comune di Ciampino",
        provider="brave",
        fetched_at=datetime.now(timezone.utc) - timedelta(days=30),
        results=[WebResult(title=p.title, url=p.url) for p in PAGINE],
    )
    monkeypatch.setattr(respond, "load_websearch", lambda _query: entry_scaduta)

    chiamate: list[str] = []

    async def ricerca_fresca(*, comune_sito, query):
        chiamate.append(query)
        return list(PAGINE), None

    monkeypatch.setattr(respond, "_ricerca_a_gradini", ricerca_fresca)

    risposta = _chiedi_informazione(monkeypatch=monkeypatch)

    assert chiamate == ["urp comune di Ciampino"]
    assert [r.url for r in risposta.info.web_results] == [r.url for r in PAGINE]


def test_brave_non_configurato_per_ente_coperto_risposta_onesta(
    ente_coperto_ma_esaurito: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anche sul ramo dell'ente coperto: niente eccezione al cittadino."""
    monkeypatch.setattr(respond, "leggi_orari_urp", lambda _comune: SOLO_HTML)
    monkeypatch.setattr(respond, "_websearch_query", lambda *, topic, ente: "urp comune di Ciampino")
    monkeypatch.setattr(respond, "load_websearch", lambda _query: None)

    async def niente_motore(*, comune_sito, query):
        return [], "La ricerca sul web non è disponibile in questo momento."

    monkeypatch.setattr(respond, "_ricerca_a_gradini", niente_motore)

    risposta = _chiedi_informazione(monkeypatch=monkeypatch)

    assert risposta is not None
    assert risposta.info.web_results == []
    assert any("non è disponibile" in riga for riga in risposta.info.diagnosis)
