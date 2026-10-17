import sqlite3

import pytest

from dagi_core.agent import Agent
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import Tool, ToolRegistry, ToolResult


class FakeProvider:
    def __init__(self):
        self.requests = []

    def stream(self, messages, _tools):
        self.requests.append(messages)
        return iter([
            StreamEvent(kind="text", text="Continued."),
            StreamEvent(kind="finish", finish_reason="stop"),
        ])


class RecordingTools(ToolRegistry):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return f"executed {name}"


def _prepare_tool_round(state, session_id, run_id, calls, recovery_metadata=None):
    state.save_tool_round(
        session_id,
        run_id,
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call["id"], "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": __import__("json").dumps(call["arguments"]),
                    },
                }
                for call in calls
            ],
        },
        calls,
        recovery_metadata=recovery_metadata,
    )


def test_pending_call_is_safe_to_resume_after_crash_before_action(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session = state.create_session()
    interrupted_run = state.create_run(session)
    call = {"id": "call-safe", "name": "custom", "arguments": {"value": 1}}
    _prepare_tool_round(state, session, interrupted_run, [call])
    state.close()

    state = StateStore(path)
    state.recover_interrupted(session)
    tools = RecordingTools(tmp_path / "workspace", state, session)
    events = list(Agent(FakeProvider(), tools, state, session).run_turn("resume"))

    assert tools.calls == [("custom", {"value": 1})]
    assert state.get_tool_call("call-safe")["status"] == "succeeded"
    assert state.get_run(interrupted_run)["status"] == "error"
    assert events[-1].status == "completed"
    state.close()


def test_unknown_outcome_is_never_replayed_on_resume(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session = state.create_session()
    interrupted_run = state.create_run(session)
    call = {"id": "call-unknown", "name": "custom", "arguments": {}}
    _prepare_tool_round(state, session, interrupted_run, [call])
    state.mark_tool_call_running("call-unknown")
    state.close()

    state = StateStore(path)
    state.recover_interrupted(session)
    tools = RecordingTools(tmp_path / "workspace", state, session)
    events = list(Agent(FakeProvider(), tools, state, session).run_turn("resume"))

    assert tools.calls == []
    assert state.get_tool_call("call-unknown")["status"] == "uncertain"
    assert events[-1].status == "error"
    assert "unknown outcome" in events[-2].text
    state.close()


def test_recovery_resumes_only_pending_sibling_after_completed_tool(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session = state.create_session()
    interrupted_run = state.create_run(session)
    calls = [
        {"id": "call-first", "name": "first", "arguments": {}},
        {"id": "call-second", "name": "second", "arguments": {}},
    ]
    _prepare_tool_round(state, session, interrupted_run, calls)
    state.mark_tool_call_running("call-first")
    state.append_message(session, {
        "role": "tool", "tool_call_id": "call-first", "name": "first", "content": "first result",
    })
    state.finish_tool_call("call-first", "succeeded", "first result")
    state.close()

    state = StateStore(path)
    state.recover_interrupted(session)
    tools = RecordingTools(tmp_path / "workspace", state, session)
    events = list(Agent(FakeProvider(), tools, state, session).run_turn("resume"))

    assert tools.calls == [("second", {})]
    assert state.get_tool_call("call-first")["status"] == "succeeded"
    assert state.get_tool_call("call-second")["status"] == "succeeded"
    tool_events = [event for event in events if event.kind == "tool_call"]
    assert [event.tool_call_id for event in tool_events] == ["call-second"]
    state.close()


def test_running_call_with_legacy_saved_result_without_outcome_is_uncertain(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session = state.create_session()
    interrupted_run = state.create_run(session)
    call = {"id": "call-result", "name": "custom", "arguments": {}}
    _prepare_tool_round(state, session, interrupted_run, [call])
    state.mark_tool_call_running("call-result")
    state.append_message(session, {
        "role": "tool", "tool_call_id": "call-result", "name": "custom", "content": "saved result",
    })
    state.close()

    state = StateStore(path)
    state.recover_interrupted(session)

    recovered = state.get_tool_call("call-result")
    assert recovered is not None
    assert recovered["status"] == "uncertain"
    assert recovered["result"] == "saved result"
    assert "explicit persisted outcome" in recovered["error"]
    state.close()


def test_legacy_tool_message_without_explicit_outcome_stays_uncertain(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session = state.create_session()
    run = state.create_run(session)
    _prepare_tool_round(state, session, run, [{"id": "legacy-result", "name": "custom", "arguments": {}}])
    state.mark_tool_call_running("legacy-result")
    state.append_message(session, {
        "role": "tool", "tool_call_id": "legacy-result", "name": "custom",
        "content": "arbitrary output that may actually describe a failure",
    })
    state.close()

    state = StateStore(path)
    state.recover_interrupted(session)
    recovered = state.get_tool_call("legacy-result")
    assert recovered is not None
    assert recovered["status"] == "uncertain"
    assert recovered["result"] == "arbitrary output that may actually describe a failure"
    assert "explicit persisted outcome" in recovered["error"]
    state.close()


def test_tool_completion_persists_message_outcome_and_event_atomically(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    run = state.create_run(session)
    _prepare_tool_round(state, session, run, [{"id": "atomic-result", "name": "custom", "arguments": {}}])
    state.mark_tool_call_running("atomic-result")
    event = {
        "kind": "tool_result", "session_id": session, "run_id": run,
        "tool_call_id": "atomic-result", "tool_name": "custom", "text": "done", "is_error": False,
    }

    state.complete_tool_call(session, run, "atomic-result", "succeeded", "done", None, event)

    completed = state.get_tool_call("atomic-result")
    assert completed is not None and completed["status"] == "succeeded"
    assert any(m.get("tool_call_id") == "atomic-result" and m["content"] == "done" for m in state.messages(session))
    assert any(row["event"]["kind"] == "tool_result" for row in state.list_run_events(run))
    state.close()


def test_tool_completion_rolls_back_if_persisted_event_is_invalid(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    run = state.create_run(session)
    _prepare_tool_round(state, session, run, [{"id": "atomic-failure", "name": "custom", "arguments": {}}])
    state.mark_tool_call_running("atomic-failure")
    bad_event = {
        "kind": "tool_result", "session_id": session, "run_id": run,
        "tool_call_id": "atomic-failure", "unserializable": object(),
    }

    with pytest.raises(TypeError):
        state.complete_tool_call(session, run, "atomic-failure", "succeeded", "done", None, bad_event)

    failed = state.get_tool_call("atomic-failure")
    assert failed is not None and failed["status"] == "running"
    assert not any(m.get("tool_call_id") == "atomic-failure" for m in state.messages(session))
    assert state.list_run_events(run) == []
    state.close()


def test_tool_recovery_metadata_survives_restart(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session = state.create_session()
    run = state.create_run(session)
    call = {"id": "call-metadata", "name": "custom", "arguments": {}}
    _prepare_tool_round(
        state, session, run, [call],
        recovery_metadata={"call-metadata": {"retryable": True, "has_verifier": True}},
    )
    state.close()

    state = StateStore(path)
    persisted = state.get_tool_call("call-metadata")

    assert persisted["retryable"] is True
    assert persisted["has_verifier"] is True
    state.close()


def test_safe_retry_policy_replays_only_declared_idempotent_tool(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session = state.create_session()
    interrupted_run = state.create_run(session)
    call = {"id": "call-idempotent", "name": "custom_retry", "arguments": {"value": 3}}
    _prepare_tool_round(
        state, session, interrupted_run, [call],
        recovery_metadata={"call-idempotent": {"retryable": True, "has_verifier": False}},
    )
    state.mark_tool_call_running("call-idempotent")
    state.close()

    state = StateStore(path)
    state.recover_interrupted(session)
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    calls = []
    tools.register(Tool(
        "custom_retry", "Safe custom operation.", {"type": "object"},
        lambda args: calls.append(args["value"]) or ToolResult("retried"), retryable=True,
    ))
    events = list(Agent(FakeProvider(), tools, state, session).run_turn("resume"))

    assert calls == [3]
    assert state.get_tool_call("call-idempotent")["status"] == "succeeded"
    assert events[-1].status == "completed"
    state.close()


def test_effect_verifier_resolves_unknown_action_without_replay(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session = state.create_session()
    interrupted_run = state.create_run(session)
    call = {"id": "call-verified", "name": "custom_verified", "arguments": {"key": "value"}}
    _prepare_tool_round(
        state, session, interrupted_run, [call],
        recovery_metadata={"call-verified": {"retryable": False, "has_verifier": True}},
    )
    state.mark_tool_call_running("call-verified")
    state.close()

    state = StateStore(path)
    state.recover_interrupted(session)
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    executions = []
    tools.register(Tool(
        "custom_verified", "Effect can be checked.", {"type": "object"},
        lambda _args: executions.append("executed") or ToolResult("new effect"),
        verify_effect=lambda args: args["key"] == "value",
    ))

    events = list(Agent(FakeProvider(), tools, state, session).run_turn("resume"))

    assert executions == []
    assert state.get_tool_call("call-verified")["status"] == "succeeded"
    assert any(event.tool_call_id == "call-verified" and event.is_error is False for event in events)
    assert any("verified after interruption" in message["content"] for message in state.messages(session) if message["role"] == "tool")
    state.close()


def test_existing_tool_execution_table_migrates_recovery_metadata(tmp_path):
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, title TEXT, created_at TEXT NOT NULL);
        CREATE TABLE runs (run_id TEXT PRIMARY KEY, session_id INTEGER NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, error TEXT);
        CREATE TABLE tool_executions (
            tool_call_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_id INTEGER NOT NULL,
            name TEXT NOT NULL, arguments TEXT NOT NULL, status TEXT NOT NULL,
            result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO sessions VALUES(1, 'old', '2026-01-01T00:00:00+00:00');
        INSERT INTO runs VALUES('old-run', 1, 'error', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00', 'interrupted');
        INSERT INTO tool_executions VALUES('old-call', 'old-run', 1, 'old_tool', '{}', 'pending', NULL, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
    """)
    connection.commit()
    connection.close()

    state = StateStore(path)
    old_call = state.get_tool_call("old-call")

    assert old_call["retryable"] is False
    assert old_call["has_verifier"] is False
    state.close()
