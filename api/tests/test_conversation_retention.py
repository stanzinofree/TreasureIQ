"""R1: the app must actually run ``purge_expired`` — not just define it.

The store-level tests in ``test_conversation_store.py`` prove the purge query
is correct; these prove the wiring: entering the app lifespan drops expired
conversations at startup. The original defect was a correct ``purge_expired``
that no code path ever called.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from treasureiq.api import app, conversation_store
from treasureiq.conversation import CONVERSATION_TTL


def _scadi(conversation_id: str) -> None:
    scaduto = (
        datetime.now(timezone.utc) - CONVERSATION_TTL - timedelta(seconds=1)
    ).isoformat()
    with conversation_store._connect() as db:
        db.execute(
            "UPDATE conversations SET last_seen_at = ? WHERE conversation_id = ?",
            (scaduto, conversation_id),
        )


def _esiste(conversation_id: str) -> bool:
    with conversation_store._connect() as db:
        row = db.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    return row is not None


def test_startup_purges_expired_conversation() -> None:
    scaduta = conversation_store.open()
    conversation_store.append_message(scaduta.conversation_id, "user", "vecchia")
    attiva = conversation_store.open()
    conversation_store.append_message(attiva.conversation_id, "user", "viva")
    _scadi(scaduta.conversation_id)

    # Entering the lifespan runs the deterministic startup purge.
    with TestClient(app):
        pass

    assert not _esiste(scaduta.conversation_id)
    assert _esiste(attiva.conversation_id)

    conversation_store.forget(attiva.conversation_id)
