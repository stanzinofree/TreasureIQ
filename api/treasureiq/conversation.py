"""Anonymous, reopenable conversation storage.

This store is independent from the legacy mock-SPID profile cookie.  A
conversation identifier is an opaque random token; all state remains
server-side and ``forget`` deletes messages and events immediately.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONVERSATION_TTL = timedelta(days=90)
TOKEN_BYTES = 32


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    created_at: datetime
    last_seen_at: datetime


class ConversationStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    conversation_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (conversation_id, sequence),
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
                );
                CREATE TABLE IF NOT EXISTS conversation_events (
                    conversation_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (conversation_id, sequence),
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
                );
                """
            )

    def open(self, conversation_id: str | None = None) -> Conversation:
        now = _now()
        if conversation_id:
            current = self._get(conversation_id)
            if current is not None and now - current.last_seen_at <= CONVERSATION_TTL:
                with self._connect() as db:
                    db.execute(
                        "UPDATE conversations SET last_seen_at = ? WHERE conversation_id = ?",
                        (_iso(now), conversation_id),
                    )
                return Conversation(conversation_id, current.created_at, now)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        with self._connect() as db:
            db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?)",
                (token, _iso(now), _iso(now)),
            )
        return Conversation(token, now, now)

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("conversation message role must be user or assistant")
        if not content.strip():
            raise ValueError("conversation message cannot be empty")
        now = _now()
        with self._connect() as db:
            self._require_live(db, conversation_id, now)
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?)",
                (conversation_id, sequence, role, content, _iso(now)),
            )
            db.execute(
                "UPDATE conversations SET last_seen_at = ? WHERE conversation_id = ?",
                (_iso(now), conversation_id),
            )

    def append_event(self, conversation_id: str, event_type: str, payload: str) -> None:
        if not event_type.strip():
            raise ValueError("conversation event type cannot be empty")
        now = _now()
        with self._connect() as db:
            self._require_live(db, conversation_id, now)
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM conversation_events WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO conversation_events VALUES (?, ?, ?, ?, ?)",
                (conversation_id, sequence, event_type, payload, _iso(now)),
            )

    def forget(self, conversation_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM conversation_messages WHERE conversation_id = ?", (conversation_id,))
            db.execute("DELETE FROM conversation_events WHERE conversation_id = ?", (conversation_id,))
            db.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))

    def purge_expired(self) -> int:
        threshold = _iso(_now() - CONVERSATION_TTL)
        with self._connect() as db:
            ids = [row[0] for row in db.execute("SELECT conversation_id FROM conversations WHERE last_seen_at < ?", (threshold,))]
            for conversation_id in ids:
                db.execute("DELETE FROM conversation_messages WHERE conversation_id = ?", (conversation_id,))
                db.execute("DELETE FROM conversation_events WHERE conversation_id = ?", (conversation_id,))
                db.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
        return len(ids)

    def _get(self, conversation_id: str) -> Conversation | None:
        with self._connect() as db:
            row = db.execute("SELECT conversation_id, created_at, last_seen_at FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
        return Conversation(row[0], _parse(row[1]), _parse(row[2])) if row else None

    def _require_live(self, db: sqlite3.Connection, conversation_id: str, now: datetime) -> None:
        row = db.execute("SELECT last_seen_at FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
        if row is None or now - _parse(row[0]) > CONVERSATION_TTL:
            raise KeyError("conversation is missing or expired")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA foreign_keys = ON")
        return db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
