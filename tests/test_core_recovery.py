from dagi_core.agent import Agent
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import ToolRegistry


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


def _prepare_tool_round(state, session_id, run_id, calls):
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
