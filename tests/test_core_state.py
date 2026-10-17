import os
import sqlite3
import stat

from dagi_core.state import StateStore


def test_session_messages_survive_reopen_and_keep_tool_call_pairing(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = StateStore(path)
    session = store.create_session("kernel")
    store.append_message(session, {"role": "user", "content": "write a file"})
    assistant = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "write_file", "arguments": '{"path":"a.txt"}'}}
        ],
    }
    store.append_message(session, assistant)
    store.append_message(session, {"role": "tool", "tool_call_id": "call-1", "name": "write_file", "content": "saved"})
    store.close()

    reopened = StateStore(path)
    assert reopened.messages(session) == [
        {"role": "user", "content": "write a file"},
        assistant,
        {"role": "tool", "tool_call_id": "call-1", "name": "write_file", "content": "saved"},
    ]
    reopened.close()


def test_full_text_search_is_literal_and_returns_session_context(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    first = store.create_session()
    second = store.create_session()
    store.append_message(first, {"role": "user", "content": 'ship with "quotes" and syntax'})
    store.append_message(second, {"role": "user", "content": "different topic"})

    hits = store.search_memory('"quotes" AND syntax')

    assert len(hits) == 1
    assert hits[0]["session_id"] == first
    assert hits[0]["role"] == "user"
    store.close()


def test_skills_can_be_created_loaded_and_listed(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")

    skill = store.create_skill(
        "release-check", "Verify a release", ["release", "tag"], "1. run tests\n2. tag"
    )

    assert store.get_skill("release-check")["body"].startswith("1. run tests")
    assert store.list_skills()[0]["name"] == skill["name"]
    store.close()


def test_run_statuses_are_persisted_and_terminal_outcomes_are_distinct(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    session = store.create_session()

    outcomes = {}
    for status in ("completed", "error", "limit", "cancelled"):
        run_id = store.create_run(session)
        assert store.get_run(run_id)["status"] == "running"
        store.finish_run(run_id, status)
        outcomes[status] = store.get_run(run_id)

    assert {run["status"] for run in outcomes.values()} == {
        "completed", "error", "limit", "cancelled"
    }
    assert all(run["session_id"] == session for run in outcomes.values())
    assert all(run["finished_at"] for run in outcomes.values())
    store.close()


def test_existing_database_migrates_partial_message_flag(tmp_path):
    path = tmp_path / "previous.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, created_at TEXT NOT NULL);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', tool_calls TEXT,
            tool_call_id TEXT, name TEXT, created_at TEXT NOT NULL
        );
        INSERT INTO sessions(title, created_at) VALUES('old', '2026-01-01T00:00:00+00:00');
    """)
    connection.commit()
    connection.close()

    store = StateStore(path)
    session = store.list_sessions()[0]["id"]
    store.append_message(session, {"role": "assistant", "content": "partial", "is_partial": True})

    assert store.messages(session, include_metadata=True)[0]["is_partial"] is True
    store.close()


def test_run_events_are_persisted_and_resumable_by_cursor(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    session = store.create_session()
    run = store.create_run(session)
    first = {"kind": "text", "session_id": session, "run_id": run, "text": "hi"}
    second = {"kind": "done", "session_id": session, "run_id": run, "status": "completed"}

    first_id = store.append_run_event(session, run, first)
    second_id = store.append_run_event(session, run, second)

    assert store.list_run_events(run, after_id=0)[0]["event"] == first
    replayed = store.list_run_events(run, after_id=first_id)
    assert len(replayed) == 1
    assert replayed[0]["id"] == second_id
    assert replayed[0]["event"] == second
    assert second_id > first_id
    store.close()


def test_legacy_run_rows_migrate_to_agent_and_budget_fields(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, title TEXT, created_at TEXT NOT NULL);
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error TEXT
        );
        INSERT INTO sessions(id, title, created_at) VALUES(1, 'legacy session', '2026-01-01T00:00:00Z');
        INSERT INTO runs(run_id, session_id, status, started_at)
        VALUES('legacy-run', 1, 'completed', '2026-01-01T00:00:00Z');
    """)
    connection.close()

    store = StateStore(path)
    legacy = store.get_run("legacy-run")

    assert legacy is not None
    assert legacy["agent_id"] == "dagi"
    assert legacy["parent_run_id"] is None
    assert legacy["depth"] == 0
    assert legacy["budget_group_id"] == "legacy-run"
    assert legacy["agent_name"] == "dagi"
    store.close()


def test_child_runs_inherit_parent_budget_scope_and_keep_separate_usage(tmp_path):
    from decimal import Decimal

    store = StateStore(tmp_path / "state.sqlite3")
    parent_session = store.create_session("parent")
    parent_run = store.create_run(parent_session)
    child_session = store.create_session("child")
    child_run = store.create_run(
        child_session, agent_id="child-agent-id", parent_run_id=parent_run, agent_name="child-model"
    )
    parent_call = store.create_provider_call(parent_run, "parent-model", "agent")
    child_call = store.create_provider_call(child_run, "child-model", "agent")
    store.record_usage(parent_call, {"source": "actual", "input_tokens": 10, "output_tokens": 2, "cost_usd": "0.01"})
    store.record_usage(child_call, {"source": "actual", "input_tokens": 20, "output_tokens": 3, "cost_usd": "0.02"})

    child = store.get_run(child_run)
    parent = store.get_run(parent_run)
    assert child is not None and parent is not None
    assert child["parent_run_id"] == parent_run
    assert child["agent_id"] == "child-agent-id"
    assert child["agent_id"] != parent["agent_id"]
    assert child["depth"] == 1
    assert child["agent_name"] == "child-model"
    assert child["budget_group_id"] == parent_run
    assert store.count_child_runs_in_budget_group(parent_run) == 1
    assert store.usage_summary(child_run)["provider_calls"] == 1
    assert store.usage_summary_for_budget(child_run)["provider_calls"] == 2
    assert store.usage_summary_for_budget(child_run)["cost_usd"] == Decimal("0.03")
    store.close()


def test_state_database_has_owner_only_permissions_on_posix(tmp_path):
    if os.name != "posix":
        return
    path = tmp_path / "private" / "state.sqlite3"
    store = StateStore(path)
    store.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
