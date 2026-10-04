from fastapi.testclient import TestClient

from treasureiq.api import app
from treasureiq.chat import respond as respond_mod
from treasureiq.chat.intent import ChatIntent, Topic
from treasureiq.conversation import ConversationStore


class _Model:
    async def aparse(self, *, system, user, output_model):
        return ChatIntent(topic=Topic.SCONOSCIUTO)


def test_chat_cookie_reopens_forget_deletes_and_next_chat_rotates_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: _Model())
    monkeypatch.setattr(
        "treasureiq.api.conversation_store",
        ConversationStore(tmp_path / "conversation.sqlite"),
    )
    client = TestClient(app)

    # Il token vive SOLO nel cookie httponly, mai nel body: la continuita' di
    # sessione si prova leggendolo dal cookie jar, che e' il vero meccanismo.
    first = client.post("/api/chat", json={"message": "ciao"})
    first_id = client.cookies.get("tiq_conversation")
    second = client.post("/api/chat", json={"message": "ancora"})

    assert first.status_code == 200
    assert first_id
    assert "conversation_id" not in first.json()  # il token non torna nel body
    # Chat successive nella stessa sessione riusano lo stesso token (cookie).
    assert client.cookies.get("tiq_conversation") == first_id
    assert "tiq_conversation" in first.headers.get("set-cookie", "")

    forgotten = client.delete("/api/conversation")
    third = client.post("/api/chat", json={"message": "nuova chat"})

    assert forgotten.status_code == 200
    assert forgotten.json() == {"status": "forgotten"}
    # Dopo il forget il cookie e' azzerato: la nuova chat apre una nuova
    # conversazione con un token diverso.
    assert client.cookies.get("tiq_conversation") != first_id
    assert "conversation_id" not in third.json()


def test_get_conversation_restores_transcript(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: _Model())
    monkeypatch.setattr(
        "treasureiq.api.conversation_store",
        ConversationStore(tmp_path / "conversation.sqlite"),
    )
    first_client = TestClient(app)
    first = first_client.post("/api/chat", json={"message": "ciao"})
    conversation_id = first_client.cookies.get("tiq_conversation")
    second = first_client.post("/api/chat", json={"message": "dove trovo l'anagrafe?"})
    assert second.status_code == 200, second.text
    assert first_client.cookies.get("tiq_conversation") == conversation_id
    assert "Max-Age=7776000" in first.headers["set-cookie"]

    reopened = TestClient(app)
    reopened.cookies.set("tiq_conversation", conversation_id)
    transcript = reopened.get("/api/conversation")

    assert transcript.status_code == 200
    messages = transcript.json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "ciao"),
        ("assistant", first.json()["reply"]),
        ("user", "dove trovo l'anagrafe?"),
        ("assistant", second.json()["reply"]),
    ]
    assert messages[0]["response"] is None
    assert messages[1]["response"] == first.json()
    assert messages[3]["response"] == second.json()
    assert all(m["created_at"] for m in messages)
    assert "conversation_id" not in str(messages)


def test_get_conversation_without_cookie_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "treasureiq.api.conversation_store",
        ConversationStore(tmp_path / "conversation.sqlite"),
    )
    response = TestClient(app).get("/api/conversation")
    assert response.status_code == 200
    assert response.json() == {"messages": []}


def test_legacy_turn_without_snapshot_remains_readable(tmp_path, monkeypatch) -> None:
    store = ConversationStore(tmp_path / "legacy.sqlite")
    monkeypatch.setattr("treasureiq.api.conversation_store", store)
    conversation_id = store.open().conversation_id
    store.append_message(conversation_id, "user", "Dove si trova l'URP?")
    store.append_message(conversation_id, "assistant", "Contatta l'URP del Comune.")
    client = TestClient(app)
    client.cookies.set("tiq_conversation", conversation_id)

    messages = client.get("/api/conversation").json()["messages"]
    assert messages[1]["content"] == "Contatta l'URP del Comune."
    assert messages[1]["response"] is None


def test_cookie_secure_flag_gates_secure_attribute(monkeypatch, tmp_path) -> None:
    """COOKIE_SECURE=True marca il cookie Secure; default (dev) no.

    `COOKIE_SECURE` e' un globale del modulo letto da `set_cookie` a runtime:
    patcharlo prova il gate senza ricaricare il modulo (che romperebbe l'app
    condivisa dagli altri test). Env spento -> niente Secure su http locale.
    """
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: _Model())
    monkeypatch.setattr(
        "treasureiq.api.conversation_store",
        ConversationStore(tmp_path / "secure.sqlite"),
    )

    monkeypatch.setattr("treasureiq.api.COOKIE_SECURE", True)
    secure = TestClient(app).post("/api/chat", json={"message": "ciao"})
    assert "Secure" in secure.headers.get("set-cookie", "")

    monkeypatch.setattr("treasureiq.api.COOKIE_SECURE", False)
    plain = TestClient(app).post("/api/chat", json={"message": "ciao"})
    assert "Secure" not in plain.headers.get("set-cookie", "")
