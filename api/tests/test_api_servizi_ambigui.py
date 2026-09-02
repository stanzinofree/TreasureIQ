"""API — round-trip del contratto ≥2: `ChatIn.servizio_scelto` e
`ChatOut.servizi_ambigui` (Ramo 3, disambiguazione multiservizio).

Due lati, nessuna rete:
  * PROIEZIONE ≥2: una `ChatAnswer` con `servizi_ambigui` (build_chat_answer
    stubbato) deve arrivare intatta al JSON del client come `servizi_ambigui`
    raggruppato — l'A6/L-3 ricorrente (un campo nello schema che nessuno riempie);
  * SELEZIONE: un turno con `servizio_scelto` (service_id opaco + service_key)
    bypassa il routing per topic e risolve a UN servizio (`seleziona_servizio`
    stubbato); un id ignoto → miss onesto URP; un body malformato → 422 Pydantic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

import treasureiq.api as api
from treasureiq.catalog.contracts import ConnectorRef
from treasureiq.catalog.service_contracts import (
    ResolvedService,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceReference,
)
from treasureiq.chat import respond as respond_mod
from treasureiq.chat.intent import ChatIntent, QuestionKind, Topic
from treasureiq.chat.respond import (
    ChatAnswer,
    GruppoServiziAmbigui,
    ServiziAmbigui,
    VoceServizioAmbiguo,
)
from treasureiq.mappa_connettore import MappaConnettore

ISTAT = "022018"
BASE_URL = "https://www.comune.bocenago.tn.it"
CONN = ConnectorRef(name="openpa_service", version="1")


class _ModelloFinto:
    def __init__(self, intento: ChatIntent) -> None:
        self._intento = intento

    async def aparse(self, *, system, user, output_model):
        return self._intento


def _client(monkeypatch) -> TestClient:
    provider = _ModelloFinto(ChatIntent(topic=Topic.SCONOSCIUTO))
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: provider)
    return TestClient(api.app)


def _mappa() -> MappaConnettore:
    return MappaConnettore(
        codice_istat=ISTAT,
        nome="Bocenago",
        sito=BASE_URL,
        sondato_il="2026-09-02T09:00:00+00:00",
        piattaforma_id="openpa",
    )


# -- proiezione ≥2 → ChatOut.servizi_ambigui --------------------------------


def _answer_ambigua() -> ChatAnswer:
    gruppi = [
        GruppoServiziAmbigui(
            intento="calcolatore",
            etichetta="Calcola l'importo",
            voci=[
                VoceServizioAmbiguo(
                    service_id=f"{ISTAT}:openpa:869",
                    title="Calcolatore IMIS",
                    url=f"{BASE_URL}/servizi/869",
                )
            ],
        ),
        GruppoServiziAmbigui(
            intento="agevolazione",
            etichetta="Chiedi un'agevolazione",
            voci=[
                VoceServizioAmbiguo(
                    service_id=f"{ISTAT}:openpa:417",
                    title="Domanda di agevolazione tributaria (IMIS)",
                    url=f"{BASE_URL}/servizi/417",
                )
            ],
        ),
    ]
    return ChatAnswer(
        reply="Per Bocenago il comune pubblica più servizi; scegli qui accanto.",
        topic=Topic.MODULISTICA,
        kind=QuestionKind.INFORMAZIONE,
        data_gap="servizio_ambiguo",
        needs_clarification=True,
        matches=[],
        spid_required=False,
        spid_reason=None,
        access_mode=None,
        citizen_effort=1,
        info=None,
        servizi_ambigui=ServiziAmbigui(service_key="tributi_imu", gruppi=gruppi),
    )


def test_servizi_ambigui_proiettati_nel_json(monkeypatch) -> None:
    async def _finto(**kwargs):
        return _answer_ambigua()

    # build_chat_answer è importato nel namespace di `api`: si patcha lì.
    monkeypatch.setattr(api, "build_chat_answer", _finto)
    client = _client(monkeypatch)

    risposta = client.post("/api/chat", json={"message": "modulistica IMU"})
    assert risposta.status_code == 200, risposta.text
    sa = risposta.json()["servizi_ambigui"]
    assert sa is not None, "ChatOut.servizi_ambigui vuoto: A6/L-3 di nuovo"
    assert sa["service_key"] == "tributi_imu"
    intenti = [g["intento"] for g in sa["gruppi"]]
    assert intenti == ["calcolatore", "agevolazione"]
    voce = sa["gruppi"][0]["voci"][0]
    assert voce["service_id"] == f"{ISTAT}:openpa:869"
    assert voce["title"] == "Calcolatore IMIS"
    assert voce["url"].endswith("/servizi/869")
    assert sa["gruppi"][0]["etichetta"] == "Calcola l'importo"


def test_niente_servizi_ambigui_nel_caso_normale(monkeypatch) -> None:
    client = _client(monkeypatch)
    risposta = client.post("/api/chat", json={"message": "ciao"})
    assert risposta.status_code == 200, risposta.text
    assert risposta.json()["servizi_ambigui"] is None


# -- selezione: ChatIn.servizio_scelto → seleziona_servizio -----------------


def _resolved() -> ResolvedService:
    url = f"{BASE_URL}/servizi/869"
    ref = ServiceReference(
        service_id=f"{ISTAT}:openpa:869",
        title="Calcolatore IMIS",
        source_url=url,
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION, url=url, source_url=url
            ),
        ),
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return ResolvedService(
        reference=ref,
        retrieved_at=datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc),
        from_cache=False,
        connector=CONN,
    )


def test_selezione_id_noto_risolve_scheda(monkeypatch) -> None:
    visti = {}

    def _seleziona(request, *, mappa, service_id, **kw):
        visti["service_id"] = service_id
        return _resolved()

    monkeypatch.setattr("treasureiq.mappa_connettore._da_cache", lambda _i: _mappa())
    monkeypatch.setattr(respond_mod, "seleziona_servizio", _seleziona)
    client = _client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={
            "message": "come pago l'IMU",
            "comune_istat": ISTAT,
            "servizio_scelto": {
                "service_id": f"{ISTAT}:openpa:869",
                "service_key": "tributi_imu",
            },
        },
    )
    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["servizi_ambigui"] is None
    assert corpo["info"] is not None
    assert corpo["info"]["service"] is not None
    assert corpo["info"]["service"]["service_id"] == f"{ISTAT}:openpa:869"
    assert visti["service_id"] == f"{ISTAT}:openpa:869"


def test_selezione_id_ignoto_miss_urp(monkeypatch) -> None:
    monkeypatch.setattr("treasureiq.mappa_connettore._da_cache", lambda _i: _mappa())
    monkeypatch.setattr(respond_mod, "seleziona_servizio", lambda *a, **kw: None)
    client = _client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={
            "message": "come pago l'IMU",
            "comune_istat": ISTAT,
            "servizio_scelto": {
                "service_id": f"{ISTAT}:openpa:99999",
                "service_key": "tributi_imu",
            },
        },
    )
    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["info"] is None
    assert corpo["servizi_ambigui"] is None
    assert "URP" in corpo["reply"]


def test_servizio_scelto_malformato_e_422(monkeypatch) -> None:
    client = _client(monkeypatch)
    risposta = client.post(
        "/api/chat",
        json={
            "message": "come pago l'IMU",
            "comune_istat": ISTAT,
            # service_key mancante: 422 automatico di Pydantic, mai alla logica.
            "servizio_scelto": {"service_id": f"{ISTAT}:openpa:869"},
        },
    )
    assert risposta.status_code == 422, risposta.text
