"""Persistent, searchable conversation memory backed by SQLite + FTS5.

Every message from every session is written here, so `search_memory` can
pull relevant context from months-old conversations back into the current
one -- the "long-term memory" half of the learning loop.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    summary TEXT,
    started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    session_id UNINDEXED,
    role UNINDEXED,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, session_id, role)
    VALUES (new.id, new.content, new.session_id, new.role);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, session_id, role)
    VALUES ('delete', old.id, old.content, old.session_id, old.role);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, session_id, role)
    VALUES ('delete', old.id, old.content, old.session_id, old.role);
    INSERT INTO messages_fts(rowid, content, session_id, role)
    VALUES (new.id, new.content, new.session_id, new.role);
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionInfo:
    id: int
    title: str | None
    summary: str | None
    started_at: str


@dataclass
class MessageRecord:
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


@dataclass
class SearchHit:
    message_id: int
    session_id: int
    role: str
    snippet: str
    created_at: str


class MemoryStore:
    """Not process-safe (SQLite + a Python lock only helps within one
    process) but safe to share across threads of the same process -- the
    web dashboard runs a single worker process with several threads against
    one MemoryStore instance.
    """

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if os.name == "posix":
            os.chmod(db_path, 0o600)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_session(self, title: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions (title, summary, started_at) VALUES (?, ?, ?)",
                (title, None, _now()),
            )
            self._conn.commit()
            return cur.lastrowid

    def add_message(self, session_id: int, role: str, content: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, _now()),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_messages(self, session_id: int) -> list[MessageRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, session_id, role, content, created_at FROM messages "
                "WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            return [MessageRecord(**dict(r)) for r in rows]

    def set_session_summary(self, session_id: int, summary: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET summary = ? WHERE id = ?", (summary, session_id)
            )
            self._conn.commit()

    def list_sessions(self, limit: int = 20) -> list[SessionInfo]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, summary, started_at FROM sessions "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [SessionInfo(**dict(r)) for r in rows]

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        # Treat the whole query as a literal phrase so FTS5 operator syntax
        # (AND/OR/NOT/quotes/etc.) in free-form user text can't raise a
        # "malformed MATCH expression" error.
        safe_query = '"' + query.replace('"', '""') + '"'
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT m.id AS message_id, m.session_id AS session_id, m.role AS role,
                       snippet(messages_fts, 0, '[', ']', '...', 12) AS snippet,
                       m.created_at AS created_at
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, limit),
            ).fetchall()
            return [SearchHit(**dict(r)) for r in rows]
