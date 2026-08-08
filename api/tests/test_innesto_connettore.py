"""B4: innesto del connettore nel flusso chat + endpoint di analisi on-demand.

Quattro casi, nessuna rete:

1. `leggi_connettore` risponde con un `EsitoConnettore` ricco -> la risposta
   porta i recapiti VERBATIM, `access_mode` M4_CONNETTORE, niente più il
   vecchio «NIENTE DI PUBBLICATO».
2. `leggi_connettore` risponde `None` -> il gradino web resta invariato
   (A7/D-06): nessuna regressione per i comuni senza connettore.
3. Sinonimo anagrafe -> servizi demografici, ufficio con solo centralino
   (nessun telefono diretto pubblicato): risposta onesta, niente numero
   inventato (D-04/D-05).
4. `/api/at-analisi` con un host esterno al comune -> rifiutato dalla
   guardia (D-08, niente SSRF).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from treasureiq.api import app
from treasureiq.chat import respond
from treasureiq.chat.intent import ChatIntent, QuestionKind, Topic
from treasureiq.connettore import EsitoConnettore, UfficioConnettore
from treasureiq.integration import AccessMode
from treasureiq.sonda_live import ComuneNoto

CIAMPINO = ComuneNoto(
    codice_istat="058118",
    nome="Ciampino",
    provincia="RM",
    regione="Lazio",
    sito="www.comune.ciampino.roma.it",
)


def _esito_ricco() -> EsitoConnettore:
    return EsitoConnettore(
        codice_istat=CIAMPINO.codice_istat,
        piattaforma="municipium",
        letto_il="2026-08-08T10:00:00+00:00",
        uffici=[
            UfficioConnettore(
                nome="Servizi Demografici",
                url="https://www.comune.ciampino.roma.it/servizi-demografici",
                telefoni=["06 1234567"],
                email=["demografici@comune.ciampino.roma.it"],
                pec=[],
                orari="lun-ven 9-13",
                source_typed=True,
                letto_il="2026-08-08T10:00:00+00:00",
            )
        ],
    )


def _esito_solo_centralino() -> EsitoConnettore:
    return EsitoConnettore(
        codice_istat=CIAMPINO.codice_istat,
        piattaforma="municipium",
        letto_il="2026-08-08T10:00:00+00:00",
        uffici=[
            UfficioConnettore(
                nome="Servizi Demografici",
                url="https://www.comune.ciampino.roma.it/servizi-demografici",
                telefoni=[],
                email=[],
                pec=[],
                orari=None,
                source_typed=True,
                letto_il="2026-08-08T10:00:00+00:00",
            )
        ],
    )


def _chiedi(*, parole: str, monkeypatch: pytest.MonkeyPatch, esito: EsitoConnettore | None):
    monkeypatch.setattr(respond, "risolvi_comune", lambda _hint: CIAMPINO)
    monkeypatch.setattr(respond, "comune_per_codice", lambda _codice: CIAMPINO)
    monkeypatch.setattr(respond.connettore, "leggi_connettore", lambda *_a, **_k: esito)
    return asyncio.run(
        respond._risposta_live(
            hint="Ciampino",
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            comune_istat=CIAMPINO.codice_istat,
            parole=parole,
        )
    )


def test_connettore_ricco_precede_il_web_e_mostra_recapiti_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        respond,
        "_cerca_sul_web",
        lambda _query: (_ for _ in ()).throw(AssertionError("non doveva cercare sul web")),
    )

    risposta = _chiedi(parole="ufficio anagrafe", monkeypatch=monkeypatch, esito=_esito_ricco())

    assert risposta is not None
    assert risposta.access_mode == AccessMode.M4_CONNETTORE.value
    assert risposta.info is not None
    assert risposta.info.office is not None
    assert risposta.info.office.telefono == "06 1234567"
    assert risposta.info.office.email == "demografici@comune.ciampino.roma.it"
    assert "NIENTE DI PUBBLICATO" not in risposta.reply
    assert "06 1234567" in risposta.reply
    # L-3: la card strutturata (B5) legge `esito_connettore`, non `reply`.
    assert risposta.esito_connettore is not None
    assert risposta.esito_connettore.uffici[0].telefoni == ["06 1234567"]


def test_connettore_assente_lascia_invariato_il_gradino_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from treasureiq.ingest.websearch import WebResult

    pagine = [WebResult(url="https://example.org/urp", title="URP Ciampino", snippet="orari")]
    monkeypatch.setattr(respond, "_cerca_sul_web", lambda _query: (list(pagine), None))

    risposta = _chiedi(parole="ufficio anagrafe", monkeypatch=monkeypatch, esito=None)

    assert risposta is not None
    assert risposta.access_mode == AccessMode.M6_WEB_APERTO.value
    assert [r.url for r in risposta.info.web_results] == [r.url for r in pagine]
    assert risposta.esito_connettore is None


def test_sinonimo_anagrafe_servizi_demografici_niente_telefono_inventato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        respond,
        "_cerca_sul_web",
        lambda _query: (_ for _ in ()).throw(AssertionError("non doveva cercare sul web")),
    )

    risposta = _chiedi(
        parole="ufficio anagrafe", monkeypatch=monkeypatch, esito=_esito_solo_centralino()
    )

    assert risposta is not None
    assert risposta.access_mode == AccessMode.M4_CONNETTORE.value
    assert risposta.info.office is not None
    assert risposta.info.office.telefono is None
    # Onestà campo-per-campo (D-05): nessun numero — né diretto né di un
    # centralino generico spacciato per linea diretta — compare nel testo.
    assert not any(ch.isdigit() for ch in risposta.reply)


def test_at_analisi_rifiuta_host_esterno(monkeypatch: pytest.MonkeyPatch) -> None:
    import treasureiq.api as api_module

    monkeypatch.setattr(api_module, "comune_per_codice", lambda _codice: CIAMPINO)

    client = TestClient(app)
    risposta = client.post(
        "/api/at-analisi",
        json={
            "codice_istat": CIAMPINO.codice_istat,
            "pdf_url": "https://sito-estraneo.example.com/bando.pdf",
        },
    )

    assert risposta.status_code == 400


def test_at_analisi_ha_il_rate_limit_del_modello() -> None:
    """DoS: `/api/at-analisi` scarica e apre PDF arbitrari (via `pdf_url`,
    dentro il dominio del comune) — deve portare la stessa dependency di
    `/api/chat` (`limita_modello`), non restare l'unica rotta costosa senza
    limite."""
    import treasureiq.api as api_module

    rotta = next(r for r in app.routes if getattr(r, "path", None) == "/api/at-analisi")
    nomi_dipendenze = {
        dep.call.__name__
        for dep in rotta.dependant.dependencies
        if dep.call is not None
    }
    assert api_module.limita_modello.__name__ in nomi_dipendenze


def test_chatout_proietta_esito_connettore(monkeypatch: pytest.MonkeyPatch) -> None:
    """L-3: `ChatOut` deve portare `esito_connettore` (nome esatto, letto da
    B5), popolato quando il ramo connettore scatta e `None` altrimenti — non
    solo nel testo `reply`, ma nel campo strutturato serializzato."""
    import treasureiq.api as api_module

    esito = _esito_ricco()
    presente = api_module.ChatOut.model_construct(esito_connettore=esito)
    assente = api_module.ChatOut.model_construct(esito_connettore=None)

    assert "esito_connettore" in api_module.ChatOut.model_fields

    dump_presente = presente.model_dump(include={"esito_connettore"})
    assert dump_presente["esito_connettore"] is not None
    assert dump_presente["esito_connettore"]["uffici"][0]["telefoni"] == ["06 1234567"]

    dump_assente = assente.model_dump(include={"esito_connettore"})
    assert dump_assente["esito_connettore"] is None
