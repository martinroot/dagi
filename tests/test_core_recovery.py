import sqlite3

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


def test_running_call_with_saved_result_is_reconciled_as_completed(tmp_path):
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

    assert state.get_tool_call("call-result")["status"] == "succeeded"
    assert state.get_tool_call("call-result")["result"] == "saved result"
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
