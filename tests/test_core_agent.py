from copy import deepcopy
from pathlib import Path

from dagi_core.agent import Agent, AgentEvent
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import ToolRegistry


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def stream(self, messages, tools):
        self.requests.append(deepcopy(messages))
        return iter(self.responses.pop(0))


class InspectingTools(ToolRegistry):
    def call(self, name, arguments):
        history = self.state.messages(self.session_id)
        assert any(message.get("tool_calls") for message in history)
        return super().call(name, arguments)


def test_agent_persists_tool_call_before_side_effect_then_continues(tmp_path: Path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    workspace = tmp_path / "workspace"
    tools = InspectingTools(workspace, state, session)
    provider = FakeProvider([
        [StreamEvent(kind="tool_call", tool_call={
            "id": "call-1", "name": "write_file",
            "arguments": {"path": "hello.txt", "content": "from minimal core"},
        })],
        [StreamEvent(kind="text", text="Saved.")],
    ])
    agent = Agent(provider, tools, state, session)

    events = list(agent.run_turn("save hello.txt"))

    assert (workspace / "hello.txt").read_text() == "from minimal core"
    assert [message["role"] for message in state.messages(session)] == ["user", "assistant", "tool", "assistant"]
    assert provider.requests[1][-1]["role"] == "tool"
    assert events[-1].kind == "done"
    assert events[-1].session_id == session
    assert events[-1].run_id
    assert all(event.session_id == session for event in events)
    assert all(event.run_id == events[0].run_id for event in events)
    assert next(event for event in events if event.kind == "tool_call").tool_call_id == "call-1"
    assert next(event for event in events if event.kind == "tool_result").tool_call_id == "call-1"
    assert state.get_run(events[-1].run_id)["status"] == "completed"
    assert any(event.kind == "tool_result" for event in events)
    assert any(event.kind == "text" and event.text == "Saved." for event in events)
    state.close()


def test_agent_returns_tool_error_without_skipping_follow_up(tmp_path: Path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    provider = FakeProvider([
        [StreamEvent(kind="tool_call", tool_call={
            "id": "call-1", "name": "unknown", "arguments": {},
        })],
        [StreamEvent(kind="text", text="I could not run that tool.")],
    ])

    events = list(Agent(provider, tools, state, session).run_turn("try tool"))

    assert provider.requests.__len__() == 2
    assert any("unknown tool" in (event.text or "") for event in events)
    assert events[-1].kind == "done"
    state.close()


def test_provider_error_and_tool_round_limit_have_distinct_run_statuses(tmp_path, monkeypatch):
    class FailingProvider:
        def stream(self, *_args):
            raise RuntimeError("network failed")

    error_state = StateStore(tmp_path / "error.sqlite3")
    error_session = error_state.create_session()
    error_tools = ToolRegistry(tmp_path / "error-workspace", error_state, error_session)
    error_events = list(Agent(FailingProvider(), error_tools, error_state, error_session).run_turn("hello"))
    error_run = error_state.get_run(error_events[0].run_id)
    assert error_run["status"] == "error"
    assert "network failed" in next(event for event in error_events if event.kind == "error").text
    error_state.close()

    monkeypatch.setattr("dagi_core.agent.MAX_TOOL_ROUNDS", 1)
    limit_state = StateStore(tmp_path / "limit.sqlite3")
    limit_session = limit_state.create_session()
    limit_tools = ToolRegistry(tmp_path / "limit-workspace", limit_state, limit_session)
    provider = FakeProvider([[
        StreamEvent(kind="tool_call", tool_call={"id": "call-limit", "name": "unknown", "arguments": {}})
    ]])
    limit_events = list(Agent(provider, limit_tools, limit_state, limit_session).run_turn("loop"))
    limit_run = limit_state.get_run(limit_events[0].run_id)
    assert limit_run["status"] == "limit"
    assert limit_run["status"] != error_run["status"]
    limit_state.close()


def test_closing_a_live_run_marks_it_cancelled(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    provider = FakeProvider([[StreamEvent(kind="text", text="partial")]])
    events = Agent(provider, tools, state, session).run_turn("hello")

    first_event = next(events)
    events.close()

    assert first_event.run_id
    assert state.get_run(first_event.run_id)["status"] == "cancelled"
    state.close()
