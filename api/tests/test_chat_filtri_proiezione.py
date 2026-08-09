"""Ciclo 11 (B3, innesto backend): `riconosci_filtri` è ora la sola sorgente

degli slot di profilo, e il contratto `Filtro` deve arrivare intatto fino al
JSON del cliente (`ChatOut.filtri`, A6/L-3 — bug ricorrente: un campo
aggiunto al modello ma mai popolato nell'endpoint).

Tre casi, nessuna rete (Ollama mockato con lo stesso idioma di
`test_chat_bandi.py`/`test_intent_guardie.py` — un `_ModelloFinto.aparse`
che restituisce un `ChatIntent` gia' pronto, letto per duck-typing dai soli
campi che D-01 lascia al modello: `topic`/`kind`/`comune_hint`/
`beneficiary_role`):

1. Un messaggio con eta'/ISEE/disabilita' espliciti produce `filtri` non
   vuoto nel JSON, e ogni `span.testo` e' una sottostringa VERBATIM del
   messaggio (il cittadino deve potersi riconoscere in quello che il testo
   ha letto).
2. `filtri_override` con `chiave: "disabilita"` toglie quel filtro dal
   ricalcolo — l'A8 di ciclo 11: correggere un'evidenza letta ma sbagliata,
   senza reinventare un valore diverso (A12).
3. Una chiave fuori dal catalogo chiuso `FiltroChiave` (es. "admin_bypass")
   e' un 422 automatico di Pydantic — non arriva mai a toccare la logica.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from treasureiq.api import app
from treasureiq.chat import respond as respond_mod
from treasureiq.chat.intent import ChatIntent, Topic


class _ModelloFinto:
    """Stesso idioma di `test_chat_bandi.py`: nessuna rete, l'intento e'
    gia' quello che il modello *avrebbe* prodotto."""

    def __init__(self, intento: ChatIntent) -> None:
        self._intento = intento

    async def aparse(self, *, system, user, output_model):
        return self._intento


def _monta_client(monkeypatch) -> TestClient:
    provider = _ModelloFinto(ChatIntent(topic=Topic.SCONOSCIUTO))
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: provider)
    return TestClient(app)


def test_filtri_popolati_e_span_verbatim(monkeypatch) -> None:
    client = _monta_client(monkeypatch)
    messaggio = "ho 67 anni e ISEE 9.360, sono disabile"

    risposta = client.post("/api/chat", json={"message": messaggio})

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    filtri = corpo["filtri"]
    assert filtri, "ChatOut.filtri e' vuoto: il bug ricorrente A6/L-3 e' tornato"
    for filtro in filtri:
        span = filtro["span"]
        if span is not None:
            assert span["testo"] in messaggio, (filtro, messaggio)


def test_filtri_override_rimuove_disabilita_dal_ricalcolo(monkeypatch) -> None:
    client = _monta_client(monkeypatch)
    messaggio = "ho 67 anni e ISEE 9.360, sono disabile"

    risposta = client.post(
        "/api/chat",
        json={
            "message": messaggio,
            "filtri_override": [{"chiave": "disabilita", "azione": "rimuovi"}],
        },
    )

    assert risposta.status_code == 200, risposta.text
    chiavi = {f["chiave"] for f in risposta.json()["filtri"]}
    assert "disabilita" not in chiavi, chiavi


def test_filtri_override_chiave_fuori_catalogo_e_422(monkeypatch) -> None:
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={
            "message": "ho 67 anni",
            "filtri_override": [{"chiave": "admin_bypass"}],
        },
    )

    assert risposta.status_code == 422, risposta.text
