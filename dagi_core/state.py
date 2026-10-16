"""One small SQLite store for sessions, transcript, full-text search, and skills."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'error', 'limit', 'cancelled')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS tool_executions (
    tool_call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'uncertain')),
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tool_executions_session_status ON tool_executions(session_id, status);
CREATE TABLE IF NOT EXISTS provider_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    usage_source TEXT NOT NULL CHECK (usage_source IN ('actual', 'estimated', 'unavailable')),
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS provider_calls_run_id ON provider_calls(run_id, id);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,
    tool_call_id TEXT,
    name TEXT,
    created_at TEXT NOT NULL,
    is_partial INTEGER NOT NULL DEFAULT 0
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
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(messages)")}
        if "is_partial" not in columns:
            self._db.execute("ALTER TABLE messages ADD COLUMN is_partial INTEGER NOT NULL DEFAULT 0")
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

    def create_run(self, session_id: int) -> str:
        run_id = str(uuid.uuid4())
        self._db.execute(
            "INSERT INTO runs(run_id, session_id, status, started_at) VALUES(?, ?, 'running', ?)",
            (run_id, session_id, _now()),
        )
        self._db.commit()
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row is not None else None

    def finish_run(self, run_id: str, status: str, error: str | None = None) -> None:
        if status not in {"completed", "error", "limit", "cancelled"}:
            raise ValueError(f"invalid terminal run status: {status!r}")
        cursor = self._db.execute(
            "UPDATE runs SET status=?, finished_at=?, error=? WHERE run_id=? AND status='running'",
            (status, _now(), error, run_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"run is missing or already finished: {run_id}")
        self._db.commit()

    def create_provider_call(self, run_id: str, model: str, purpose: str) -> int:
        cursor = self._db.execute(
            """INSERT INTO provider_calls(run_id, model, purpose, usage_source, started_at)
               VALUES(?, ?, ?, 'unavailable', ?)""",
            (run_id, model, purpose, _now()),
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def record_usage(self, provider_call_id: int, usage: dict[str, Any]) -> None:
        source = usage.get("source")
        if source not in {"actual", "estimated", "unavailable"}:
            raise ValueError(f"invalid usage source: {source!r}")
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        cost_usd = usage.get("cost_usd")
        if source == "unavailable":
            if any(value is not None for value in (input_tokens, output_tokens, cost_usd)):
                raise ValueError("unavailable usage must not contain numeric zeroes or costs")
        else:
            for value in (input_tokens, output_tokens):
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("known usage requires non-negative integer token counts")
        cursor = self._db.execute(
            """UPDATE provider_calls SET usage_source=?, input_tokens=?, output_tokens=?,
                      cost_usd=?, finished_at=? WHERE id=?""",
            (
                source,
                input_tokens,
                output_tokens,
                str(cost_usd) if cost_usd is not None else None,
                _now(),
                provider_call_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"provider call does not exist: {provider_call_id}")
        self._db.commit()

    def list_provider_calls(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM provider_calls WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            if item["cost_usd"] is not None:
                from decimal import Decimal
                item["cost_usd"] = Decimal(item["cost_usd"])
        return result

    def usage_summary(self, run_id: str) -> dict[str, Any]:
        rows = self._db.execute(
            "SELECT usage_source, input_tokens, output_tokens, cost_usd FROM provider_calls WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
        if not rows:
            from decimal import Decimal
            return {
                "provider_calls": 0, "source": "actual", "input_tokens": 0,
                "output_tokens": 0, "cost_usd": Decimal("0"),
            }
        from decimal import Decimal
        sources = {row["usage_source"] for row in rows}
        source = "unavailable" if "unavailable" in sources else (next(iter(sources)) if len(sources) == 1 else "mixed")
        input_tokens = None if any(row["input_tokens"] is None for row in rows) else sum(row["input_tokens"] for row in rows)
        output_tokens = None if any(row["output_tokens"] is None for row in rows) else sum(row["output_tokens"] for row in rows)
        cost_usd = None if any(row["cost_usd"] is None for row in rows) else sum(
            (Decimal(row["cost_usd"]) for row in rows), Decimal("0")
        )
        return {
            "provider_calls": len(rows), "source": source,
            "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost_usd,
        }

    def save_tool_round(
        self,
        session_id: int,
        run_id: str,
        assistant_message: dict[str, Any],
        calls: list[dict[str, Any]],
    ) -> None:
        if not calls:
            raise ValueError("a tool round must contain at least one call")
        now = _now()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._insert_message(session_id, assistant_message)
            for call in calls:
                call_id = call.get("id")
                name = call.get("name")
                arguments = call.get("arguments")
                if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                    raise ValueError("tool calls require a non-empty id and name")
                if not isinstance(arguments, dict):
                    raise ValueError("tool call arguments must be an object")
                self._db.execute(
                    """INSERT INTO tool_executions
                       (tool_call_id, run_id, session_id, name, arguments, status, created_at, updated_at)
                       VALUES(?, ?, ?, ?, ?, 'pending', ?, ?)""",
                    (call_id, run_id, session_id, name, json.dumps(arguments, ensure_ascii=False), now, now),
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    def get_tool_call(self, tool_call_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM tool_executions WHERE tool_call_id=?", (tool_call_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["arguments"] = json.loads(result["arguments"])
        return result

    def list_tool_calls(
        self, session_id: int, statuses: tuple[str, ...] | None = None
    ) -> list[dict[str, Any]]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = self._db.execute(
                f"SELECT * FROM tool_executions WHERE session_id=? AND status IN ({placeholders}) ORDER BY rowid",
                (session_id, *statuses),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM tool_executions WHERE session_id=? ORDER BY rowid", (session_id,)
            ).fetchall()
        results = [dict(row) for row in rows]
        for result in results:
            result["arguments"] = json.loads(result["arguments"])
        return results

    def mark_tool_call_running(self, tool_call_id: str) -> None:
        cursor = self._db.execute(
            "UPDATE tool_executions SET status='running', updated_at=? WHERE tool_call_id=? AND status='pending'",
            (_now(), tool_call_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"tool call is missing or not pending: {tool_call_id}")
        self._db.commit()

    def finish_tool_call(
        self, tool_call_id: str, status: str, result: str | None = None, error: str | None = None
    ) -> None:
        if status not in {"succeeded", "failed", "uncertain"}:
            raise ValueError(f"invalid tool call outcome: {status!r}")
        cursor = self._db.execute(
            """UPDATE tool_executions SET status=?, result=?, error=?, updated_at=?
               WHERE tool_call_id=? AND status='running'""",
            (status, result, error, _now(), tool_call_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"tool call is missing or not running: {tool_call_id}")
        self._db.commit()

    def recover_interrupted(self, session_id: int | None = None) -> list[dict[str, Any]]:
        scope = " AND session_id=?" if session_id is not None else ""
        params = (session_id,) if session_id is not None else ()
        rows = self._db.execute(
            f"SELECT tool_call_id FROM tool_executions WHERE status='running'{scope}", params
        ).fetchall()
        for row in rows:
            call_id = row["tool_call_id"]
            saved = self._db.execute(
                "SELECT content FROM messages WHERE role='tool' AND tool_call_id=? ORDER BY id DESC LIMIT 1",
                (call_id,),
            ).fetchone()
            if saved is None:
                status, result, error = "uncertain", None, "process stopped while action was running; outcome unknown"
            else:
                result = saved["content"]
                status = "failed" if result.startswith("[tool error]") else "succeeded"
                error = None
            self._db.execute(
                "UPDATE tool_executions SET status=?, result=?, error=?, updated_at=? WHERE tool_call_id=?",
                (status, result, error, _now(), call_id),
            )
        self._db.execute(
            f"UPDATE runs SET status='error', finished_at=?, error='process interrupted' "
            f"WHERE status='running'{scope}",
            (_now(), *params),
        )
        self._db.commit()
        if session_id is None:
            return []
        return self.list_tool_calls(session_id)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id, title, created_at FROM sessions ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def _insert_message(self, session_id: int, message: dict[str, Any]) -> int:
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
            """INSERT INTO messages(session_id, role, content, tool_calls, tool_call_id, name, created_at, is_partial)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                content,
                json.dumps(calls, ensure_ascii=False) if calls is not None else None,
                message.get("tool_call_id"),
                message.get("name"),
                _now(),
                int(bool(message.get("is_partial", False))),
            ),
        )
        return int(cursor.lastrowid)

    def append_message(self, session_id: int, message: dict[str, Any]) -> int:
        message_id = self._insert_message(session_id, message)
        self._db.commit()
        return message_id

    def messages(self, session_id: int, *, include_metadata: bool = False) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """SELECT role, content, tool_calls, tool_call_id, name, is_partial
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
            if include_metadata:
                message["is_partial"] = bool(row["is_partial"])
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
