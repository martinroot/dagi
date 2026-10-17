from copy import deepcopy
import json
from pathlib import Path

from dagi_core.agent import Agent, AgentEvent
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import Tool, ToolRegistry, ToolResult


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
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "call-1", "name": "write_file",
                "arguments": {"path": "hello.txt", "content": "from minimal core"},
            }),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [StreamEvent(kind="text", text="Saved."), StreamEvent(kind="finish", finish_reason="stop")],
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
    tool_result = next(event for event in events if event.kind == "tool_result")
    assert tool_result.tool_call_id == "call-1"
    assert tool_result.is_error is False
    stored_call = state.get_tool_call("call-1")
    assert stored_call["retryable"] is True
    assert stored_call["has_verifier"] is True
    assert state.get_run(events[-1].run_id)["status"] == "completed"
    conclusion = state.list_tool_reflections(session, limit=3)[0]
    assert conclusion["trigger"] == "run_concluded"
    assert conclusion["observed"]["provider_turn_completed"] is True
    assert conclusion["observed"]["goal_status"] == "unknown"
    assert events[-1].run_id in conclusion["evidence_ids"]
    assert "call-1" in conclusion["evidence_ids"]
    assert conclusion["blocker"] is False
    assert any(event.kind == "tool_result" for event in events)
    assert any(event.kind == "text" and event.text == "Saved." for event in events)
    state.close()


def test_agent_returns_tool_error_without_skipping_follow_up(tmp_path: Path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    provider = FakeProvider([
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "call-1", "name": "unknown", "arguments": {},
            }),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [StreamEvent(kind="text", text="I could not run that tool."), StreamEvent(kind="finish", finish_reason="stop")],
    ])

    events = list(Agent(provider, tools, state, session).run_turn("try tool"))

    assert provider.requests.__len__() == 2
    assert any("unknown tool" in (event.text or "") for event in events)
    tool_result = next(event for event in events if event.kind == "tool_result")
    assert tool_result.is_error is True
    assert tool_result.outcome == "failed"
    assert events[-1].kind == "done"
    state.close()


def test_repeated_known_tool_failure_is_reflected_and_blocks_an_unchanged_retry(tmp_path):
    from dagi_core.runtime_context import RUNTIME_CONTEXT_END, RUNTIME_CONTEXT_START

    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    calls = {"count": 0}

    def fail_known(_arguments):
        calls["count"] += 1
        return ToolResult("[tool error] deterministic fixture failure", is_error=True)

    tools = ToolRegistry(tmp_path / "workspace", state, session)
    tools.register(Tool(
        "fail_known", "Fail deterministically.",
        {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        fail_known,
    ))
    provider = FakeProvider([
        [StreamEvent(kind="tool_call", tool_call={"id": "fail-1", "name": "fail_known", "arguments": {"value": "payload-marker"}}), StreamEvent(kind="finish", finish_reason="tool_calls")],
        [StreamEvent(kind="tool_call", tool_call={"id": "fail-2", "name": "fail_known", "arguments": {"value": "payload-marker"}}), StreamEvent(kind="finish", finish_reason="tool_calls")],
        [StreamEvent(kind="tool_call", tool_call={"id": "fail-3", "name": "fail_known", "arguments": {"value": "payload-marker"}}), StreamEvent(kind="finish", finish_reason="tool_calls")],
    ])

    events = list(Agent(provider, tools, state, session, repeat_failure_threshold=2).run_turn("try the action"))

    assert events[-1].status == "limit"
    assert len(provider.requests) == 3
    assert calls["count"] == 2
    system = provider.requests[2][0]["content"]
    start = system.split(RUNTIME_CONTEXT_START, 1)[1].split(RUNTIME_CONTEXT_END, 1)[0]
    snapshot = json.loads(start)
    reflection = snapshot["operational_reflections"][0]
    assert reflection["trigger"] == "repeated_tool_failure"
    assert reflection["repeat_count"] == 2
    assert "fail-1" in reflection["evidence_ids"] and "fail-2" in reflection["evidence_ids"]
    assert "fail-3" in reflection["evidence_ids"] or state.get_tool_call("fail-3")["status"] == "failed"
    assert "repeated identical tool failure" in state.get_tool_call("fail-3")["error"]
    reflection = state.list_tool_reflections(session, limit=3)[0]
    assert reflection["blocker"] is True
    assert "payload-marker" not in json.dumps(reflection)
    replay = state.record_tool_reflection(
        session_id=session,
        run_id=events[-1].run_id,
        failure_fingerprint=reflection["failure_fingerprint"],
        action_fingerprint=reflection["action_fingerprint"],
        tool_name=reflection["tool_name"],
        error_category=reflection["error_category"],
        observed=reflection["observed"],
        evidence_ids=reflection["evidence_ids"],
        repeat_count=reflection["repeat_count"],
        blocker=True,
    )
    assert replay["reflection_id"] == reflection["reflection_id"]
    assert len(state.list_tool_reflections(session, limit=3)) == 1
    other_session = state.create_session("unrelated")
    assert state.list_tool_reflections(other_session, limit=3) == []
    run_id = events[-1].run_id
    state.close()
    reopened = StateStore(tmp_path / "state.sqlite3")
    saved = reopened.list_tool_reflections(session, limit=3)[0]
    assert saved["reflection_id"] == reflection["reflection_id"]
    assert saved["repeat_count"] == 2
    assert saved["blocker"] is True
    assert reopened.get_run(run_id)["status"] == "limit"
    reopened.close()


def test_changed_arguments_do_not_share_a_tool_failure_fingerprint(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    attempts = []

    def fail_known(arguments):
        attempts.append(arguments["value"])
        return ToolResult("[tool error] deterministic fixture failure", is_error=True)

    tools = ToolRegistry(tmp_path / "workspace", state, session)
    tools.register(Tool(
        "fail_known", "Fail deterministically.",
        {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        fail_known,
    ))
    provider = FakeProvider([
        [StreamEvent(kind="tool_call", tool_call={"id": "different-1", "name": "fail_known", "arguments": {"value": "one"}}), StreamEvent(kind="finish", finish_reason="tool_calls")],
        [StreamEvent(kind="tool_call", tool_call={"id": "different-2", "name": "fail_known", "arguments": {"value": "two"}}), StreamEvent(kind="finish", finish_reason="tool_calls")],
        [StreamEvent(kind="text", text="I changed the input."), StreamEvent(kind="finish", finish_reason="stop")],
    ])

    events = list(Agent(provider, tools, state, session).run_turn("try a different value"))

    assert events[-1].status == "completed"
    assert attempts == ["one", "two"]
    assert len(provider.requests) == 3
    assert state.list_tool_reflections(session, limit=3) == []
    state.close()


def test_malformed_builtin_arguments_are_recoverable_and_do_not_block_later_turns(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "known.txt").write_text("verified input", encoding="utf-8")
    tools = ToolRegistry(workspace, state, session)
    provider = FakeProvider([
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "bad-path", "name": "read_file", "arguments": {},
            }),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "good-path", "name": "read_file", "arguments": {"path": "known.txt"},
            }),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [StreamEvent(kind="text", text="The corrected read succeeded."), StreamEvent(kind="finish", finish_reason="stop")],
        [StreamEvent(kind="text", text="The next user turn also works."), StreamEvent(kind="finish", finish_reason="stop")],
    ])
    agent = Agent(provider, tools, state, session)

    first_turn = list(agent.run_turn("read the file"))

    bad_result = next(event for event in first_turn if event.kind == "tool_result" and event.tool_call_id == "bad-path")
    assert bad_result.outcome == "failed"
    assert "missing required argument 'path'" in bad_result.text
    assert state.get_tool_call("bad-path")["status"] == "failed"
    assert len(provider.requests) == 3
    tool_message = next(message for message in provider.requests[1] if message.get("role") == "tool")
    envelope = json.loads(tool_message["content"])
    assert envelope["tool_call_id"] == "bad-path"
    assert envelope["outcome"] == "failed"
    assert "missing required argument 'path'" in envelope["content"]
    assert first_turn[-1].status == "completed"

    second_turn = list(agent.run_turn("a follow-up user message"))

    assert second_turn[-1].status == "completed"
    assert len(provider.requests) == 4
    assert any(message["role"] == "user" and message["content"] == "a follow-up user message" for message in state.messages(session))
    assert state.get_tool_call("good-path")["status"] == "succeeded"
    state.close()


def test_tool_result_event_exposes_explicit_uncertain_outcome(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)

    def crash(_arguments):
        raise RuntimeError("unexpected handler failure")

    tools.register(Tool("crash", "Raise an unexpected failure.", {"type": "object", "properties": {}}, crash))
    provider = FakeProvider([[
        StreamEvent(kind="tool_call", tool_call={"id": "call-uncertain", "name": "crash", "arguments": {}}),
        StreamEvent(kind="finish", finish_reason="tool_calls"),
    ]])
    events = list(Agent(provider, tools, state, session).run_turn("run the test tool"))
    result = next(event for event in events if event.kind == "tool_result")
    assert result.outcome == "uncertain"
    saved = next(row["event"] for row in state.list_run_events(result.run_id) if row["event"]["kind"] == "tool_result")
    assert saved["outcome"] == "uncertain"
    assert state.list_tool_reflections(session, limit=3) == []
    state.close()


def test_structured_tool_presentation_is_persisted_without_replacing_text_result(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    presentation = {
        "type": "file",
        "summary": "Read src/main.py",
        "artifacts": [{"path": "src/main.py", "operation": "read"}],
        "diagnostics": {"bytes": 12, "truncated": False},
    }
    tools.register(Tool(
        "inspect_file", "Return a structured file result.",
        {"type": "object", "properties": {}},
        lambda _arguments: ToolResult("file contents", presentation=presentation),
    ))
    provider = FakeProvider([
        [StreamEvent(kind="tool_call", tool_call={"id": "call-present", "name": "inspect_file", "arguments": {}}),
         StreamEvent(kind="finish", finish_reason="tool_calls")],
        [StreamEvent(kind="text", text="The file was read."), StreamEvent(kind="finish", finish_reason="stop")],
    ])
    events = list(Agent(provider, tools, state, session).run_turn("inspect the file"))
    stored = state.get_tool_call("call-present")
    assert stored["result"] == "file contents"
    assert stored["presentation"] == presentation
    tool_event = next(row["event"] for row in state.list_run_events(events[0].run_id) if row["event"]["kind"] == "tool_result")
    assert tool_event["presentation"] == presentation
    assert any(message["role"] == "tool" and message["content"] == "file contents" for message in state.messages(session))
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
        StreamEvent(kind="tool_call", tool_call={"id": "call-limit", "name": "unknown", "arguments": {}}),
        StreamEvent(kind="finish", finish_reason="tool_calls"),
    ]])
    limit_events = list(Agent(provider, limit_tools, limit_state, limit_session).run_turn("loop"))
    limit_run = limit_state.get_run(limit_events[0].run_id)
    assert limit_run["status"] == "limit"
    assert limit_run["status"] != error_run["status"]
    limit_state.close()


def test_agent_can_run_against_independent_sessions(tmp_path):
    class Provider:
        model = "shared-model"

        def __init__(self):
            self.requests = []

        def stream(self, messages, _tools):
            self.requests.append(deepcopy(messages))
            return iter([
                StreamEvent(kind="text", text=f"reply-{len(self.requests)}"),
                StreamEvent(kind="finish", finish_reason="stop"),
            ])

    state = StateStore(tmp_path / "state.sqlite3")
    first = state.create_session("first")
    second = state.create_session("second")
    provider = Provider()
    tool_sessions = []

    def tools_for(session_id):
        tool_sessions.append(session_id)
        return ToolRegistry(tmp_path / f"workspace-{session_id}", state, session_id)

    agent = Agent(provider, tools_for, state)
    first_events = list(agent.run_turn("first prompt", session_id=first))
    second_events = list(agent.run_turn("second prompt", session_id=second))

    assert state.messages(first)[-1]["content"] == "reply-1"
    assert state.messages(second)[-1]["content"] == "reply-2"
    first_run_id = first_events[-1].run_id
    second_run_id = second_events[-1].run_id
    assert first_run_id is not None and second_run_id is not None
    first_run = state.get_run(first_run_id)
    second_run = state.get_run(second_run_id)
    assert first_run is not None and second_run is not None
    assert first_run["session_id"] == first
    assert second_run["session_id"] == second
    assert first_run["agent_id"] == second_run["agent_id"]
    assert first_run["agent_id"] != first_run["run_id"]
    assert tool_sessions == [first, second]
    state.close()


def test_closing_a_live_run_marks_it_cancelled(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    provider = FakeProvider([[StreamEvent(kind="text", text="partial")]])
    events = Agent(provider, tools, state, session).run_turn("hello")

    started_event = next(events)
    first_event = next(events)
    events.close()

    assert started_event.kind == "started"
    assert first_event.text == "partial"
    assert first_event.run_id
    assert state.get_run(first_event.run_id)["status"] == "cancelled"
    partial = state.messages(session, include_metadata=True)[-1]
    assert state.list_run_events(first_event.run_id)[-1]["event"]["status"] == "cancelled"
    assert partial["is_partial"] is True
    state.close()


def test_length_finish_persists_partial_output_and_limit_status(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    provider = FakeProvider([[
        StreamEvent(kind="text", text="incomplete answer"),
        StreamEvent(kind="finish", finish_reason="length"),
    ]])

    events = list(Agent(provider, tools, state, session).run_turn("answer"))

    assert events[-1].status == "limit"
    assert state.get_run(events[-1].run_id)["status"] == "limit"
    partial = state.messages(session, include_metadata=True)[-1]
    assert partial["content"] == "incomplete answer"
    assert partial["is_partial"] is True
    state.close()


def test_filtered_finish_never_executes_tool_call(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    workspace = tmp_path / "workspace"
    tools = ToolRegistry(workspace, state, session)
    provider = FakeProvider([[
        StreamEvent(kind="text", text="filtered"),
        StreamEvent(kind="tool_call", tool_call={
            "id": "blocked-call", "name": "write_file",
            "arguments": {"path": "must-not-exist", "content": "no"},
        }),
        StreamEvent(kind="finish", finish_reason="content_filter"),
    ]])

    events = list(Agent(provider, tools, state, session).run_turn("do it"))

    assert not (workspace / "must-not-exist").exists()
    assert state.get_run(events[-1].run_id)["status"] == "error"
    assert state.messages(session, include_metadata=True)[-1]["is_partial"] is True
    state.close()


def test_stream_without_finish_is_saved_as_incomplete(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    provider = FakeProvider([[StreamEvent(kind="text", text="cut off")]])

    events = list(Agent(provider, tools, state, session).run_turn("continue"))

    assert state.get_run(events[-1].run_id)["status"] == "error"
    partial = state.messages(session, include_metadata=True)[-1]
    assert partial["content"] == "cut off"
    assert partial["is_partial"] is True
    state.close()


def test_cancelling_agent_closes_provider_transport(tmp_path):
    from types import SimpleNamespace as NS

    from dagi_core.provider import OpenAICompatibleProvider

    class ClosableResponse:
        def __init__(self):
            self.chunks = iter([NS(choices=[NS(delta=NS(content="streaming", tool_calls=None), finish_reason=None)], usage=None)])
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.chunks)

        def close(self):
            self.closed = True

    response = ClosableResponse()
    completions = NS(create=lambda **_kwargs: response)
    provider = OpenAICompatibleProvider("test", "fake-key")
    provider._client = NS(chat=NS(completions=completions))
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    turn = Agent(provider, tools, state, session).run_turn("hello")

    started = next(turn)
    event = next(turn)
    turn.close()

    assert started.kind == "started"
    assert event.text == "streaming"
    assert response.closed is True
    assert state.get_run(event.run_id)["status"] == "cancelled"
    state.close()
