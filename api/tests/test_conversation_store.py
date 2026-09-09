from datetime import datetime, timedelta, timezone

import pytest

from treasureiq.conversation import CONVERSATION_TTL, ConversationStore


def test_conversation_reopens_and_keeps_messages(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversation.sqlite")
    opened = store.open()
    store.append_message(opened.conversation_id, "user", "Dove trovo l'anagrafe?")
    store.append_event(opened.conversation_id, "query_planned", '{"capability":"offices"}')

    reopened = store.open(opened.conversation_id)

    assert reopened.conversation_id == opened.conversation_id
    assert reopened.last_seen_at >= opened.last_seen_at
    assert [(m.role, m.content) for m in store.messages(opened.conversation_id)] == [
        ("user", "Dove trovo l'anagrafe?")
    ]


def test_forget_deletes_conversation_immediately(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversation.sqlite")
    opened = store.open()
    store.append_message(opened.conversation_id, "user", "Dimentica questa chat")

    store.forget(opened.conversation_id)

    assert store.open(opened.conversation_id).conversation_id != opened.conversation_id


def test_expired_conversation_is_not_reopened(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversation.sqlite")
    opened = store.open()
    with store._connect() as db:
        expired = (datetime.now(timezone.utc) - CONVERSATION_TTL - timedelta(seconds=1)).isoformat()
        db.execute("UPDATE conversations SET last_seen_at = ? WHERE conversation_id = ?", (expired, opened.conversation_id))

    replacement = store.open(opened.conversation_id)

    assert replacement.conversation_id != opened.conversation_id
    with pytest.raises(KeyError):
        store.messages(opened.conversation_id)


def test_message_role_is_closed(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversation.sqlite")
    opened = store.open()

    with pytest.raises(ValueError, match="role"):
        store.append_message(opened.conversation_id, "system", "non ammesso")


def _scadi(store: ConversationStore, conversation_id: str) -> None:
    """Force one conversation past its TTL by backdating ``last_seen_at``."""
    scaduto = (
        datetime.now(timezone.utc) - CONVERSATION_TTL - timedelta(seconds=1)
    ).isoformat()
    with store._connect() as db:
        db.execute(
            "UPDATE conversations SET last_seen_at = ? WHERE conversation_id = ?",
            (scaduto, conversation_id),
        )


def _conta(store: ConversationStore, tabella: str, conversation_id: str) -> int:
    with store._connect() as db:
        return db.execute(
            f"SELECT COUNT(*) FROM {tabella} WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]


def test_purge_expired_removes_conversation_with_messages_and_events(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversation.sqlite")
    opened = store.open()
    store.append_message(opened.conversation_id, "user", "Dove trovo l'anagrafe?")
    store.append_message(opened.conversation_id, "assistant", "In via Roma 1.")
    store.append_event(opened.conversation_id, "query_planned", '{"capability":"offices"}')
    _scadi(store, opened.conversation_id)

    rimosse = store.purge_expired()

    assert rimosse == 1
    # Conversazione, messaggi ed eventi collegati spariscono insieme.
    assert _conta(store, "conversations", opened.conversation_id) == 0
    assert _conta(store, "conversation_messages", opened.conversation_id) == 0
    assert _conta(store, "conversation_events", opened.conversation_id) == 0


def test_purge_expired_keeps_active_conversations(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversation.sqlite")
    attiva = store.open()
    store.append_message(attiva.conversation_id, "user", "Ancora viva")
    scaduta = store.open()
    store.append_message(scaduta.conversation_id, "user", "Vecchia")
    store.append_event(scaduta.conversation_id, "query_planned", "{}")
    _scadi(store, scaduta.conversation_id)

    rimosse = store.purge_expired()

    assert rimosse == 1
    # L'attiva resta intatta e riapribile; la scaduta sparisce del tutto.
    assert _conta(store, "conversations", attiva.conversation_id) == 1
    assert _conta(store, "conversation_messages", attiva.conversation_id) == 1
    assert store.open(attiva.conversation_id).conversation_id == attiva.conversation_id
    assert _conta(store, "conversations", scaduta.conversation_id) == 0
    assert _conta(store, "conversation_events", scaduta.conversation_id) == 0


def test_purge_expired_noop_when_all_active(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversation.sqlite")
    opened = store.open()
    store.append_message(opened.conversation_id, "user", "Fresca")

    assert store.purge_expired() == 0
    assert _conta(store, "conversation_messages", opened.conversation_id) == 1
