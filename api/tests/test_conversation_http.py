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

    first = client.post("/api/chat", json={"message": "ciao"})
    first_id = first.json()["conversation_id"]
    second = client.post("/api/chat", json={"message": "ancora"})

    assert first.status_code == 200
    assert second.json()["conversation_id"] == first_id
    assert "tiq_conversation" in first.headers.get("set-cookie", "")

    forgotten = client.delete("/api/conversation")
    third = client.post("/api/chat", json={"message": "nuova chat"})

    assert forgotten.status_code == 200
    assert forgotten.json() == {"status": "forgotten"}
    assert third.json()["conversation_id"] != first_id


def test_get_conversation_restores_transcript(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: _Model())
    monkeypatch.setattr(
        "treasureiq.api.conversation_store",
        ConversationStore(tmp_path / "conversation.sqlite"),
    )
    first_client = TestClient(app)
    first = first_client.post("/api/chat", json={"message": "ciao"})
    conversation_id = first.json()["conversation_id"]
    second = first_client.post("/api/chat", json={"message": "dove trovo l'anagrafe?"})
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id
    assert "Max-Age=7776000" in first.headers["set-cookie"]

    reopened = TestClient(app)
    reopened.cookies.set("tiq_conversation", conversation_id)
    transcript = reopened.get("/api/conversation")

    assert transcript.status_code == 200
    assert transcript.json() == {
        "conversation_id": conversation_id,
        "messages": [
            {"role": "user", "content": "ciao"},
            {"role": "assistant", "content": first.json()["reply"]},
            {"role": "user", "content": "dove trovo l'anagrafe?"},
            {"role": "assistant", "content": second.json()["reply"]},
        ],
    }


def test_get_conversation_without_cookie_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "treasureiq.api.conversation_store",
        ConversationStore(tmp_path / "conversation.sqlite"),
    )
    response = TestClient(app).get("/api/conversation")
    assert response.status_code == 200
    assert response.json() == {"conversation_id": None, "messages": []}
