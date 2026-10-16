"""One small SQLite store for sessions, transcript, full-text search, and skills."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,
    tool_call_id TEXT,
    name TEXT,
    created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, session_id UNINDEXED, role UNINDEXED,
    content='messages', content_rowid='id'
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
CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    triggers TEXT NOT NULL DEFAULT '[]',
    body TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _skill_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    if not name:
        raise ValueError("skill name must contain letters or digits")
    return name[:80]


class StateStore:
    """Thread-confined database handle. All transcript and skill state lives in one file."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._db.commit()
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def close(self) -> None:
        self._db.close()

    def create_session(self, title: str | None = None) -> int:
        cursor = self._db.execute(
            "INSERT INTO sessions(title, created_at) VALUES(?, ?)", (title, _now())
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id, title, created_at FROM sessions ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def append_message(self, session_id: int, message: dict[str, Any]) -> int:
        role = message.get("role")
        if role not in {"user", "assistant", "tool"}:
            raise ValueError(f"unsupported message role: {role!r}")
        content = message.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise TypeError("the minimal core stores text-only message content")
        calls = message.get("tool_calls")
        if calls is not None and not isinstance(calls, list):
            raise TypeError("tool_calls must be a list")
        cursor = self._db.execute(
            """INSERT INTO messages(session_id, role, content, tool_calls, tool_call_id, name, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                content,
                json.dumps(calls, ensure_ascii=False) if calls is not None else None,
                message.get("tool_call_id"),
                message.get("name"),
                _now(),
            ),
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def messages(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """SELECT role, content, tool_calls, tool_call_id, name
               FROM messages WHERE session_id=? ORDER BY id""",
            (session_id,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            message: dict[str, Any] = {"role": row["role"], "content": row["content"]}
            if row["tool_calls"] is not None:
                message["tool_calls"] = json.loads(row["tool_calls"])
                if not message["content"]:
                    message["content"] = None
            if row["tool_call_id"] is not None:
                message["tool_call_id"] = row["tool_call_id"]
            if row["name"] is not None:
                message["name"] = row["name"]
            result.append(message)
        return result

    def search_memory(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        literal = '"' + query.replace('"', '""') + '"'
        rows = self._db.execute(
            """SELECT m.id, m.session_id, m.role,
                      snippet(messages_fts, 0, '[', ']', '…', 12) AS snippet,
                      m.created_at
               FROM messages_fts JOIN messages AS m ON m.id=messages_fts.rowid
               WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?""",
            (literal, max(1, min(int(limit), 100))),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_skill(
        self, name: str, description: str, triggers: list[str], body: str
    ) -> dict[str, Any]:
        slug = _skill_name(name)
        if not description.strip() or not body.strip():
            raise ValueError("skill description and body must not be empty")
        cleaned_triggers = [str(item).strip() for item in triggers if str(item).strip()]
        self._db.execute(
            "INSERT INTO skills(name, description, triggers, body, created_at) VALUES(?, ?, ?, ?, ?)",
            (slug, description.strip(), json.dumps(cleaned_triggers, ensure_ascii=False), body.strip(), _now()),
        )
        self._db.commit()
        return self.get_skill(slug)  # type: ignore[return-value]

    def get_skill(self, name: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM skills WHERE name=?", (_skill_name(name),)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["triggers"] = json.loads(result["triggers"])
        return result

    def list_skills(self) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM skills ORDER BY use_count DESC, name").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["triggers"] = json.loads(item["triggers"])
            result.append(item)
        return result

    def record_skill_use(self, name: str) -> bool:
        cursor = self._db.execute(
            "UPDATE skills SET use_count=use_count+1 WHERE name=?", (_skill_name(name),)
        )
        self._db.commit()
        return cursor.rowcount > 0
