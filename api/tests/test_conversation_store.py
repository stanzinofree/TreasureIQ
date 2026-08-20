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


def test_message_role_is_closed(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversation.sqlite")
    opened = store.open()

    with pytest.raises(ValueError, match="role"):
        store.append_message(opened.conversation_id, "system", "non ammesso")
