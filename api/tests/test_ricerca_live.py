"""Il gradino 3 di D-32: cercare sul web per un comune fuori copertura.

Nessuna rete qui dentro. La sonda e il motore di ricerca sono sostituiti,
perché quello che va tenuto fermo non è cosa risponde oggi SearXNG — che
cambia domani — ma il patto che la risposta stringe con il cittadino:

* si cerca SOLO dopo che il portale ha risposto e non si è lasciato leggere;
* quello che torna non è mai un nostro dato, e la scheda lo dice per iscritto;
* un motore giù è una risposta in meno, mai una domanda fallita.

Il caso vero da cui nascono è Ciampino (058118): portale raggiungibile, uffici
non esposti in una forma leggibile, e una pagina URP che un motore trova al
primo colpo.
"""

from __future__ import annotations

import asyncio

import pytest

from treasureiq.chat import respond
from treasureiq.chat.intent import Topic
from treasureiq.ingest.censimento import Indirizzabilita, RecuperabilitaOrari
from treasureiq.integration import AccessMode
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
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: list(PAGINE))

    risposta = _chiedi(parole="mi dici i numeri dell'ufficio anagrafe?")

    assert risposta is not None
    assert risposta.access_mode == AccessMode.M6_WEB_APERTO.value
    assert [r.url for r in risposta.info.web_results] == [r.url for r in PAGINE]


def test_la_provenienza_resta_scritta_nella_scheda(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il punto dell'intera funzione: trovato non è letto, e si deve vedere."""
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: list(PAGINE))

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


def test_niente_dal_motore_non_diventa_niente_al_mondo(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-15: zero risultati non è una misura, è un'assenza di misura.

    Si torna alla risposta precedente — «il portale non si lascia leggere» —
    che è vera, invece di dichiarare che su quell'argomento non esiste nulla.
    """
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: [])

    risposta = _chiedi(parole="orari dell'ufficio anagrafe")

    assert risposta.access_mode == AccessMode.M4_CONNETTORE.value
    assert risposta.info.web_results == []


def test_un_motore_giu_non_fa_fallire_la_domanda(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def esplode(_query: str) -> list[respond.WebResultAnswer]:
        raise RuntimeError("searxng irraggiungibile")

    monkeypatch.setattr(respond, "search_web", lambda *a, **k: esplode(""))

    risposta = _chiedi(parole="orari dell'ufficio anagrafe")

    assert risposta is not None
    assert risposta.access_mode == AccessMode.M4_CONNETTORE.value


def test_la_query_usa_l_ufficio_che_il_cittadino_ha_nominato(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La query si compone da campi, mai dal modello — e l'ufficio nominato
    vale più del frammento generico del topic."""
    viste: list[str] = []

    def registra(query: str) -> list[respond.WebResultAnswer]:
        viste.append(query)
        return list(PAGINE)

    monkeypatch.setattr(respond, "_cerca_sul_web", registra)

    _chiedi(parole="mi dici i numeri dell'ufficio anagrafe?")

    assert viste == ["ufficio anagrafe comune di Ciampino contatti orari"]


def test_senza_ufficio_nominato_si_cerca_l_urp(
    portale_muto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    viste: list[str] = []
    monkeypatch.setattr(
        respond, "_cerca_sul_web", lambda q: (viste.append(q), list(PAGINE))[1]
    )

    _chiedi(parole="a chi posso chiedere?", topic=Topic.SCONOSCIUTO)

    assert viste == ["URP ufficio relazioni con il pubblico comune di Ciampino"]
