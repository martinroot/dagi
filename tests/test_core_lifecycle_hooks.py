"""Lifecycle hooks: constructor-only, denial-safe, and side-effect aware."""
from copy import deepcopy
from pathlib import Path

import pytest

from dagi_core.agent import Agent
from dagi_core.hooks import LifecycleHooks
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


def tool_round():
    return [
        StreamEvent(kind="tool_call", tool_call={
            "id": "call-1", "name": "write_file",
            "arguments": {"path": "notes.txt", "content": "from hook"},
        }),
        StreamEvent(kind="finish", finish_reason="tool_calls"),
    ]


def final_round():
    return [
        StreamEvent(kind="text", text="Done."),
        StreamEvent(kind="finish", finish_reason="stop"),
    ]


def make_agent(tmp_path: Path, hooks: LifecycleHooks, responses):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    provider = FakeProvider(responses)
    return state, session, tools, Agent(provider, tools, state, session, hooks=hooks), provider


def test_before_tool_denial_skips_side_effect_and_records_structured_failure(tmp_path):
    seen = []

    def deny(name, arguments):
        seen.append((name, arguments))

    def refuse(name, arguments):
        raise RuntimeError("policy says no")

    hooks = LifecycleHooks(before_tool=refuse)
    state, session, tools, agent, provider = make_agent(
        tmp_path, hooks, [tool_round(), final_round()]
    )
    events = list(agent.run_turn("write the file"))

    assert seen == []
    assert not (tools.workspace / "notes.txt").exists()
    call = state.get_tool_call("call-1")
    assert call["status"] == "failed"
    assert "before_tool" in call["error"]
    assert "policy says no" in call["error"]
    result = next(event for event in events if event.kind == "tool_result")
    assert result.is_error is True
    assert result.outcome == "failed"
    assert events[-1].status == "completed"
    assert len(provider.requests) == 2
    state.close()


def test_after_tool_failure_marks_successful_side_effect_uncertain(tmp_path):
    def fail_after(name, arguments, result):
        raise ValueError("post-effect verification unavailable")

    state, session, tools, agent, _provider = make_agent(
        tmp_path, LifecycleHooks(after_tool=fail_after), [tool_round()]
    )
    events = list(agent.run_turn("write the file"))

    # The file write really happened; the run must not claim success afterwards.
    assert (tools.workspace / "notes.txt").read_text() == "from hook"
    assert state.get_tool_call("call-1")["status"] == "uncertain"
    result = next(event for event in events if event.kind == "tool_result")
    assert result.outcome == "uncertain"
    assert "after_tool" in (result.text or "")
    assert "after_tool" in (state.get_tool_call("call-1")["error"] or "")
    assert events[-1].status == "error"
    state.close()


def test_before_model_denial_stops_before_provider_call(tmp_path):
    def deny_model(context):
        raise RuntimeError("model step disabled")

    state, session, tools, agent, provider = make_agent(
        tmp_path, LifecycleHooks(before_model=deny_model), []
    )
    events = list(agent.run_turn("anything"))

    assert provider.requests == []
    assert events[-1].status == "error"
    assert state.get_run(events[0].run_id)["status"] == "error"
    assert any("before_model" in (event.text or "") for event in events if event.kind == "error")
    state.close()


def test_hooks_are_constructor_only_and_reject_non_callables():
    with pytest.raises(ValueError, match="before_tool"):
        LifecycleHooks(before_tool="not-a-callable")
