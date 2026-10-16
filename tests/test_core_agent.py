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
    assert events[-1] == AgentEvent(kind="done")
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
