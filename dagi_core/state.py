"""One small SQLite store for sessions, transcript, full-text search, and skills."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    created_at TEXT NOT NULL,
    parent_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    workspace TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL DEFAULT 'dagi',
    parent_run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    budget_group_id TEXT NOT NULL DEFAULT '',
    agent_name TEXT NOT NULL DEFAULT 'dagi',
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
    presentation_json TEXT,
    retryable INTEGER NOT NULL DEFAULT 0,
    has_verifier INTEGER NOT NULL DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS model_requests (
    provider_call_id INTEGER PRIMARY KEY REFERENCES provider_calls(id) ON DELETE CASCADE,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS context_archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    source_message_ids TEXT NOT NULL,
    summary TEXT NOT NULL,
    compression_model TEXT NOT NULL,
    provider_call_id INTEGER NOT NULL REFERENCES provider_calls(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS context_archives_session_id ON context_archives(session_id, id);
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS run_events_run_id ON run_events(run_id, id);
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
CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    objective TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'capped', 'interrupted', 'error', 'limit')),
    iteration INTEGER NOT NULL DEFAULT 0 CHECK (iteration >= 0),
    max_iterations INTEGER NOT NULL CHECK (max_iterations BETWEEN 1 AND 10),
    feedback_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS goals_session_id ON goals(session_id, created_at);
CREATE TABLE IF NOT EXISTS goal_runs (
    goal_id TEXT NOT NULL REFERENCES goals(goal_id) ON DELETE CASCADE,
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS goal_runs_goal_id ON goal_runs(goal_id);
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    child_run_id TEXT UNIQUE NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS inbox_session_id ON inbox(session_id, id);
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
        session_columns = {row[1] for row in self._db.execute("PRAGMA table_info(sessions)")}
        if "parent_id" not in session_columns:
            self._db.execute("ALTER TABLE sessions ADD COLUMN parent_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL")
        if "workspace" not in session_columns:
            self._db.execute("ALTER TABLE sessions ADD COLUMN workspace TEXT NOT NULL DEFAULT ''")
        self._db.execute("CREATE INDEX IF NOT EXISTS sessions_parent_id ON sessions(parent_id)")
        run_columns = {row[1] for row in self._db.execute("PRAGMA table_info(runs)")}
        if "agent_id" not in run_columns:
            self._db.execute("ALTER TABLE runs ADD COLUMN agent_id TEXT NOT NULL DEFAULT 'dagi'")
        if "parent_run_id" not in run_columns:
            self._db.execute("ALTER TABLE runs ADD COLUMN parent_run_id TEXT REFERENCES runs(run_id)")
        if "depth" not in run_columns:
            self._db.execute("ALTER TABLE runs ADD COLUMN depth INTEGER NOT NULL DEFAULT 0")
        if "budget_group_id" not in run_columns:
            self._db.execute("ALTER TABLE runs ADD COLUMN budget_group_id TEXT NOT NULL DEFAULT ''")
        if "agent_name" not in run_columns:
            self._db.execute("ALTER TABLE runs ADD COLUMN agent_name TEXT NOT NULL DEFAULT 'dagi'")
        self._db.execute("UPDATE runs SET budget_group_id=run_id WHERE budget_group_id=''")
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(messages)")}
        if "is_partial" not in columns:
            self._db.execute("ALTER TABLE messages ADD COLUMN is_partial INTEGER NOT NULL DEFAULT 0")
        tool_columns = {row[1] for row in self._db.execute("PRAGMA table_info(tool_executions)")}
        if "retryable" not in tool_columns:
            self._db.execute("ALTER TABLE tool_executions ADD COLUMN retryable INTEGER NOT NULL DEFAULT 0")
        if "has_verifier" not in tool_columns:
            self._db.execute("ALTER TABLE tool_executions ADD COLUMN has_verifier INTEGER NOT NULL DEFAULT 0")
        if "presentation_json" not in tool_columns:
            self._db.execute("ALTER TABLE tool_executions ADD COLUMN presentation_json TEXT")
        self._db.commit()
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def close(self) -> None:
        self._db.close()

    def create_session(
        self,
        title: str | None = None,
        *,
        parent_id: int | None = None,
        workspace: str = "",
    ) -> int:
        if title is not None and not isinstance(title, str):
            raise ValueError("session title must be text")
        if parent_id is not None:
            if isinstance(parent_id, bool) or not isinstance(parent_id, int) or self.get_session(parent_id) is None:
                raise ValueError("parent session does not exist")
        if not isinstance(workspace, str) or len(workspace) > 4096 or "\x00" in workspace or "\\" in workspace:
            raise ValueError("session workspace must be a relative path of at most 4096 characters")
        workspace_path = PurePosixPath(workspace)
        if workspace_path.is_absolute() or ".." in workspace_path.parts:
            raise ValueError("session workspace must stay inside the configured root")
        cursor = self._db.execute(
            "INSERT INTO sessions(title, created_at, parent_id, workspace) VALUES(?, ?, ?, ?)",
            (title, _now(), parent_id, workspace),
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def create_run(
        self,
        session_id: int,
        *,
        agent_id: str = "dagi",
        parent_run_id: str | None = None,
        depth: int | None = None,
        budget_group_id: str | None = None,
        agent_name: str = "dagi",
    ) -> str:
        run_id = str(uuid.uuid4())
        if budget_group_id is not None and (not isinstance(budget_group_id, str) or not budget_group_id.strip()):
            raise ValueError("budget_group_id must be non-empty text")
        session = self.get_session(session_id)
        if session is None:
            raise ValueError("session not found")
        if parent_run_id is None:
            actual_depth = 0 if depth is None else depth
            actual_group = budget_group_id or run_id
        else:
            parent = self.get_run(parent_run_id)
            if parent is None or parent["status"] != "running":
                raise ValueError("parent run must exist and still be running")
            if session["parent_id"] != parent["session_id"]:
                raise ValueError("child session must belong to the parent run's session")
            expected_depth = int(parent["depth"]) + 1
            if depth is not None and depth != expected_depth:
                raise ValueError("child run depth must be exactly parent depth plus one")
            actual_depth = expected_depth
            inherited_group = parent["budget_group_id"] or parent_run_id
            if budget_group_id is not None and budget_group_id != inherited_group:
                raise ValueError("child run must inherit its parent's budget group")
            actual_group = inherited_group
        if actual_depth < 0:
            raise ValueError("run depth must not be negative")
        self._db.execute(
            """INSERT INTO runs(run_id, session_id, agent_id, parent_run_id, depth, budget_group_id, agent_name, status, started_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, 'running', ?)""",
            (run_id, session_id, agent_id, parent_run_id, actual_depth, actual_group, agent_name, _now()),
        )
        self._db.commit()
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_runs(self, session_id: int, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM runs WHERE session_id=? ORDER BY started_at DESC LIMIT ?",
            (session_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_child_runs(self, parent_run_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM runs WHERE parent_run_id=? ORDER BY started_at", (parent_run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def count_child_runs_in_budget_group(self, run_id: str) -> int:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"run does not exist: {run_id}")
        group_id = run["budget_group_id"] or run_id
        row = self._db.execute(
            "SELECT count(*) AS count FROM runs WHERE parent_run_id IS NOT NULL AND budget_group_id=?",
            (group_id,),
        ).fetchone()
        return int(row["count"])

    def append_run_event(self, session_id: int, run_id: str, event: dict[str, Any]) -> int:
        if event.get("session_id") != session_id or event.get("run_id") != run_id:
            raise ValueError("run event identifiers do not match the target run")
        cursor = self._db.execute(
            "INSERT INTO run_events(run_id, session_id, event_json, created_at) VALUES(?, ?, ?, ?)",
            (run_id, session_id, json.dumps(event, ensure_ascii=False), _now()),
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def list_run_events(
        self,
        run_id: str,
        *,
        after_id: int = 0,
        through_id: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        after = max(0, int(after_id))
        page_limit = max(1, min(int(limit), 5000))
        if through_id is None:
            rows = self._db.execute(
                """SELECT id, run_id, session_id, event_json, created_at FROM run_events
                   WHERE run_id=? AND id>? ORDER BY id LIMIT ?""",
                (run_id, after, page_limit),
            ).fetchall()
        else:
            through = max(0, int(through_id))
            rows = self._db.execute(
                """SELECT id, run_id, session_id, event_json, created_at FROM run_events
                   WHERE run_id=? AND id>? AND id<=? ORDER BY id LIMIT ?""",
                (run_id, after, through, page_limit),
            ).fetchall()
        return [
            {
                "id": row["id"], "run_id": row["run_id"], "session_id": row["session_id"],
                "event": json.loads(row["event_json"]), "created_at": row["created_at"],
            }
            for row in rows
        ]

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

    def save_provider_request(self, provider_call_id: int, request: dict[str, Any]) -> None:
        required = {"model", "messages", "tools", "stream", "stream_options"}
        if not required.issubset(request):
            raise ValueError(f"provider request is missing fields: {sorted(required - set(request))}")
        self._db.execute(
            "INSERT INTO model_requests(provider_call_id, request_json, created_at) VALUES(?, ?, ?)",
            (provider_call_id, json.dumps(request, ensure_ascii=False), _now()),
        )
        self._db.commit()

    def get_provider_request(self, provider_call_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT request_json FROM model_requests WHERE provider_call_id=?", (provider_call_id,)
        ).fetchone()
        return json.loads(row["request_json"]) if row is not None else None

    def save_context_archive(
        self,
        session_id: int,
        run_id: str,
        source_message_ids: list[int],
        summary: str,
        compression_model: str,
        provider_call_id: int,
    ) -> int:
        if not source_message_ids or not summary.strip():
            raise ValueError("context archives require source messages and a summary")
        cursor = self._db.execute(
            """INSERT INTO context_archives
               (session_id, run_id, source_message_ids, summary, compression_model, provider_call_id, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, run_id, json.dumps(sorted(set(source_message_ids))),
                summary.strip(), compression_model, provider_call_id, _now(),
            ),
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def list_context_archives(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM context_archives WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        archives = [dict(row) for row in rows]
        for archive in archives:
            archive["source_message_ids"] = json.loads(archive["source_message_ids"])
        return archives

    def message_records(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """SELECT id, role, content, tool_calls, tool_call_id, name, is_partial
               FROM messages WHERE session_id=? ORDER BY id""",
            (session_id,),
        ).fetchall()
        records = []
        for row in rows:
            record = dict(row)
            if record["tool_calls"] is not None:
                record["tool_calls"] = json.loads(record["tool_calls"])
            record["is_partial"] = bool(record["is_partial"])
            records.append(record)
        return records

    def usage_summary(self, run_id: str) -> dict[str, Any]:
        rows = self._db.execute(
            "SELECT usage_source, input_tokens, output_tokens, cost_usd FROM provider_calls WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
        return self._summarize_usage(rows)

    def usage_summary_for_budget(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"run does not exist: {run_id}")
        group_id = run["budget_group_id"] or run_id
        rows = self._db.execute(
            """SELECT pc.usage_source, pc.input_tokens, pc.output_tokens, pc.cost_usd
               FROM provider_calls AS pc JOIN runs AS r ON r.run_id=pc.run_id
               WHERE r.budget_group_id=? ORDER BY pc.id""",
            (group_id,),
        ).fetchall()
        return self._summarize_usage(rows)

    @staticmethod
    def _summarize_usage(rows) -> dict[str, Any]:
        from decimal import Decimal
        if not rows:
            return {
                "provider_calls": 0, "source": "actual", "input_tokens": 0,
                "output_tokens": 0, "cost_usd": Decimal("0"),
            }
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
        *,
        recovery_metadata: dict[str, dict[str, bool]] | None = None,
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
                       (tool_call_id, run_id, session_id, name, arguments, status, retryable, has_verifier, created_at, updated_at)
                       VALUES(?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
                    (
                        call_id, run_id, session_id, name, json.dumps(arguments, ensure_ascii=False),
                        int(bool((recovery_metadata or {}).get(call_id, {}).get("retryable"))),
                        int(bool((recovery_metadata or {}).get(call_id, {}).get("has_verifier"))),
                        now, now,
                    ),
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
        result["retryable"] = bool(result["retryable"])
        result["has_verifier"] = bool(result["has_verifier"])
        presentation_json = result.pop("presentation_json", None)
        result["presentation"] = json.loads(presentation_json) if presentation_json else None
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
            result["retryable"] = bool(result["retryable"])
            result["has_verifier"] = bool(result["has_verifier"])
            presentation_json = result.pop("presentation_json", None)
            result["presentation"] = json.loads(presentation_json) if presentation_json else None
        return results

    def mark_tool_call_running(self, tool_call_id: str) -> None:
        cursor = self._db.execute(
            "UPDATE tool_executions SET status='running', updated_at=? WHERE tool_call_id=? AND status='pending'",
            (_now(), tool_call_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"tool call is missing or not pending: {tool_call_id}")
        self._db.commit()

    def reset_tool_call_pending(self, tool_call_id: str) -> None:
        cursor = self._db.execute(
            "UPDATE tool_executions SET status='pending', updated_at=? WHERE tool_call_id=? AND status='running'",
            (_now(), tool_call_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"tool call is missing or not running: {tool_call_id}")
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

    def complete_tool_call(
        self,
        session_id: int,
        run_id: str,
        tool_call_id: str,
        status: str,
        result: str,
        error: str | None,
        event: dict[str, Any],
    ) -> int:
        if status not in {"succeeded", "failed", "uncertain"}:
            raise ValueError(f"invalid tool call outcome: {status!r}")
        if not isinstance(result, str) or not isinstance(event, dict):
            raise ValueError("tool completion requires text result and an event object")
        if (
            event.get("kind") != "tool_result"
            or event.get("session_id") != session_id
            or event.get("run_id") != run_id
            or event.get("tool_call_id") != tool_call_id
        ):
            raise ValueError("tool result event identifiers do not match the completion")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            call = self._db.execute(
                "SELECT * FROM tool_executions WHERE tool_call_id=?", (tool_call_id,)
            ).fetchone()
            if call is None or call["status"] != "running":
                raise ValueError(f"tool call is missing or not running: {tool_call_id}")
            current_run = self.get_run(run_id)
            if call["session_id"] != session_id or current_run is None or current_run["session_id"] != session_id:
                raise ValueError("tool completion identifiers do not match the active session")
            presentation = event.get("presentation")
            presentation_json = json.dumps(presentation, ensure_ascii=False, allow_nan=False) if presentation is not None else None
            if presentation_json is not None and len(presentation_json.encode("utf-8")) > 16_000:
                raise ValueError("tool presentation metadata exceeds 16000 bytes")
            updated = self._db.execute(
                """UPDATE tool_executions SET status=?, result=?, error=?, presentation_json=?, updated_at=?
                   WHERE tool_call_id=? AND status='running'""",
                (status, result, error, presentation_json, _now(), tool_call_id),
            )
            if updated.rowcount != 1:
                raise ValueError(f"tool call is missing or not running: {tool_call_id}")
            self._insert_message(session_id, {
                "role": "tool", "tool_call_id": tool_call_id,
                "name": call["name"], "content": result,
            })
            cursor = self._db.execute(
                "INSERT INTO run_events(run_id, session_id, event_json, created_at) VALUES(?, ?, ?, ?)",
                (run_id, session_id, json.dumps(event, ensure_ascii=False), _now()),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("tool result event insert did not return an id")
            event_id = int(cursor.lastrowid)
            self._db.commit()
            return event_id
        except BaseException:
            self._db.rollback()
            raise

    def reconcile_tool_call(
        self, tool_call_id: str, status: str, result: str | None = None, error: str | None = None
    ) -> None:
        if status not in {"pending", "succeeded", "uncertain"}:
            raise ValueError(f"invalid recovery decision: {status!r}")
        if status == "pending":
            result = None
            error = None
        cursor = self._db.execute(
            """UPDATE tool_executions SET status=?, result=?, error=?, updated_at=?
               WHERE tool_call_id=? AND status='uncertain'""",
            (status, result, error, _now(), tool_call_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"tool call is missing or not uncertain: {tool_call_id}")
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
                # A legacy tool message has no atomic outcome record; its text cannot prove success.
                status = "uncertain"
                result = saved["content"]
                error = "tool response exists without an explicit persisted outcome; verify before continuing"
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

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT id, title, created_at, parent_id, workspace FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def session_snapshot(self, session_id: int) -> dict[str, Any] | None:
        """Read session history, run state, tools, goals, and event cursors atomically."""
        self._db.execute("BEGIN")
        try:
            session = self.get_session(session_id)
            if session is None:
                self._db.commit()
                return None
            runs = self.list_runs(session_id, 100)
            event_cursors: dict[str, int] = {}
            for run in runs:
                rows = self._db.execute(
                    "SELECT id, event_json FROM run_events WHERE run_id=? ORDER BY id DESC LIMIT 2",
                    (run["run_id"],),
                ).fetchall()
                cursor = int(rows[0]["id"]) if rows else 0
                if run["status"] == "running" and rows and json.loads(rows[0]["event_json"]).get("kind") == "done":
                    cursor = int(rows[1]["id"]) if len(rows) > 1 else 0
                event_cursors[run["run_id"]] = cursor
            snapshot = {
                "session": session,
                "runs": runs,
                "messages": self.message_records(session_id),
                "tool_calls": self.list_tool_calls(session_id),
                "goals": self.list_goals(session_id),
                "event_cursors": event_cursors,
            }
            self._db.commit()
            return snapshot
        except Exception:
            self._db.rollback()
            raise

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id, title, created_at, parent_id, workspace FROM sessions ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def fork_session(self, session_id: int) -> int:
        source = self.get_session(session_id)
        if source is None:
            raise ValueError("session not found")
        if self.list_tool_calls(session_id, ("pending", "running", "uncertain")):
            raise ValueError("resolve outstanding tools before cloning")
        if any(run["status"] == "running" for run in self.list_runs(session_id)):
            raise ValueError("stop the session before cloning")
        title = (source["title"] or "Session") + " (clone)"
        clone_id = self.create_session(title, workspace=source["workspace"])
        with self._db:
            for message in self.messages(session_id, include_metadata=True):
                self._insert_message(clone_id, message)
        return clone_id

    def children(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id FROM sessions WHERE parent_id=? ORDER BY id", (session_id,)
        ).fetchall()
        children = []
        for row in rows:
            child = self.get_session(row["id"])
            if child is not None:
                children.append({"session": child, "runs": self.list_runs(child["id"], 10)})
        return children

    def notify_parent(self, child_session_id: int, run_id: str) -> None:
        child = self.get_session(child_session_id)
        run = self.get_run(run_id)
        if child is None or child["parent_id"] is None:
            return
        if run is None or run["session_id"] != child_session_id:
            raise ValueError("child run does not belong to the child session")
        answer = next((
            message["content"] for message in reversed(self.messages(child_session_id, include_metadata=True))
            if message["role"] == "assistant" and message.get("content") and not message.get("is_partial")
        ), "")
        payload = {
            "child_session_id": child_session_id,
            "run_id": run_id,
            "status": run["status"],
            "result": answer[:4_000],
            "workspace": child["workspace"],
        }
        self._db.execute(
            "INSERT OR IGNORE INTO inbox(session_id, child_run_id, payload, created_at) VALUES(?, ?, ?, ?)",
            (child["parent_id"], run_id, json.dumps(payload, ensure_ascii=False), _now()),
        )
        self._db.commit()

    def inbox(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT payload FROM inbox WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def set_session_workspace(self, session_id: int, workspace: str) -> None:
        if not isinstance(workspace, str) or "\\" in workspace or "\x00" in workspace:
            raise ValueError("session workspace must be a relative path")
        relative = PurePosixPath(workspace)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("session workspace must stay inside the configured root")
        cursor = self._db.execute("UPDATE sessions SET workspace=? WHERE id=?", (workspace, session_id))
        if cursor.rowcount != 1:
            raise ValueError("session not found")
        self._db.commit()

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

    def search_memory(
        self, query: str, limit: int = 10, *, session_id: int | None = None
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        literal = '"' + query.replace('"', '""') + '"'
        if session_id is None:
            rows = self._db.execute(
                """SELECT m.id, m.session_id, m.role,
                          snippet(messages_fts, 0, '[', ']', '…', 12) AS snippet,
                          m.created_at
                   FROM messages_fts JOIN messages AS m ON m.id=messages_fts.rowid
                   WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?""",
                (literal, max(1, min(int(limit), 100))),
            ).fetchall()
        else:
            rows = self._db.execute(
                """SELECT m.id, m.session_id, m.role,
                          snippet(messages_fts, 0, '[', ']', '…', 12) AS snippet,
                          m.created_at
                   FROM messages_fts JOIN messages AS m ON m.id=messages_fts.rowid
                   WHERE messages_fts MATCH ? AND m.session_id=? ORDER BY rank LIMIT ?""",
                (literal, session_id, max(1, min(int(limit), 100))),
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

    def create_goal(self, session_id: int, objective: str, checks: list, max_iterations: int) -> str:
        if self.get_session(session_id) is None:
            raise ValueError("session not found")
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 8_000:
            raise ValueError("goal objective must be non-empty text of at most 8000 characters")
        if not isinstance(checks, list) or not 1 <= len(checks) <= 20:
            raise ValueError("a goal requires 1..20 acceptance checks")
        if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or not 1 <= max_iterations <= 10:
            raise ValueError("max_iterations must be 1..10")
        goal_id = str(uuid.uuid4())
        now = _now()
        self._db.execute(
            """INSERT INTO goals(goal_id, session_id, objective, checks_json, status,
                      iteration, max_iterations, feedback_json, created_at, updated_at)
               VALUES(?, ?, ?, ?, 'running', 0, ?, '[]', ?, ?)""",
            (goal_id, session_id, objective.strip(), json.dumps(checks, ensure_ascii=False),
             max_iterations, now, now),
        )
        self._db.commit()
        return goal_id

    def get_goal(self, goal_id: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM goals WHERE goal_id=?", (goal_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["checks"] = json.loads(result.pop("checks_json"))
        result["feedback"] = json.loads(result.pop("feedback_json"))
        result["runs"] = [item[0] for item in self._db.execute(
            "SELECT run_id FROM goal_runs WHERE goal_id=? ORDER BY rowid", (goal_id,)
        ).fetchall()]
        return result

    def list_goals(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT goal_id FROM goals WHERE session_id=? ORDER BY created_at DESC, rowid DESC",
            (session_id,),
        ).fetchall()
        result = []
        for row in rows:
            goal = self.get_goal(row[0])
            if goal is not None:
                result.append(goal)
        return result

    def update_goal(
        self,
        goal_id: str,
        status: str,
        *,
        iteration: int | None = None,
        feedback: list | None = None,
    ) -> None:
        if status not in {"running", "completed", "capped", "interrupted", "error", "limit"}:
            raise ValueError("invalid goal status")
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError("goal not found")
        next_iteration = goal["iteration"] if iteration is None else iteration
        if isinstance(next_iteration, bool) or not isinstance(next_iteration, int) or not 0 <= next_iteration <= goal["max_iterations"]:
            raise ValueError("goal iteration is out of range")
        next_feedback = goal["feedback"] if feedback is None else feedback
        if not isinstance(next_feedback, list):
            raise ValueError("goal feedback must be a list")
        self._db.execute(
            "UPDATE goals SET status=?, iteration=?, feedback_json=?, updated_at=? WHERE goal_id=?",
            (status, next_iteration, json.dumps(next_feedback, ensure_ascii=False), _now(), goal_id),
        )
        self._db.commit()

    def link_goal_run(self, goal_id: str, run_id: str) -> None:
        goal = self.get_goal(goal_id)
        run = self.get_run(run_id)
        if goal is None or run is None:
            raise ValueError("goal and run must exist before linking")
        if goal["session_id"] != run["session_id"]:
            raise ValueError("goal run must belong to the goal session")
        self._db.execute("INSERT INTO goal_runs(goal_id, run_id) VALUES(?, ?)", (goal_id, run_id))
        self._db.commit()

    def recover_goals(self) -> int:
        cursor = self._db.execute(
            "UPDATE goals SET status='interrupted', updated_at=? WHERE status='running'",
            (_now(),),
        )
        self._db.commit()
        return cursor.rowcount

    def record_skill_use(self, name: str) -> bool:
        cursor = self._db.execute(
            "UPDATE skills SET use_count=use_count+1 WHERE name=?", (_skill_name(name),)
        )
        self._db.commit()
        return cursor.rowcount > 0
