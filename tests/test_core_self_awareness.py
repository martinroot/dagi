import json
from copy import deepcopy

from dagi_core.agent import Agent
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import ToolRegistry
from dagi_core.usage import UsagePolicy
from dagi_core.workspace import resolve_session_workspace


_CONTEXT_START = "DAGI_RUNTIME_CONTEXT_JSON_BEGIN\n"
_CONTEXT_END = "\nDAGI_RUNTIME_CONTEXT_JSON_END"


class CapturingProvider:
    model = "self-awareness-test-model"

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.requests = []

    def stream(self, messages, tools):
        self.requests.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        return iter(self.rounds.pop(0))


def _runtime_context(request):
    content = request["messages"][0]["content"]
    start = content.index(_CONTEXT_START) + len(_CONTEXT_START)
    end = content.index(_CONTEXT_END, start)
    return json.loads(content[start:end])


def test_child_request_receives_fresh_bounded_runtime_context(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    state = StateStore(tmp_path / "state.sqlite3")
    parent_session = state.create_session("parent")
    parent_run = state.create_run(parent_session, agent_id="parent-agent", agent_name="parent-model")
    state.append_message(parent_session, {"role": "user", "content": "UNRELATED_SESSION_SECRET"})
    child_session = state.create_session(
        "child", parent_id=parent_session, workspace=".dagi-children/child-17"
    )
    child_record = state.get_session(child_session)
    assert child_record is not None
    child_workspace = resolve_session_workspace(root, child_record["workspace"])
    tools = ToolRegistry(child_workspace, state, child_session)
    child_run = state.create_run(
        child_session, parent_run_id=parent_run, agent_id="child-agent", agent_name="child-model"
    )
    provider = CapturingProvider([
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "runtime-list", "name": "list_dir", "arguments": {"path": "."},
            }),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [StreamEvent(kind="text", text="Child workspace inspected."), StreamEvent(kind="finish", finish_reason="stop")],
    ])
    usage_policy = UsagePolicy(max_calls_per_run=4)
    agent = Agent(
        provider, tools, state, child_session, usage_policy=usage_policy,
        agent_id="child-agent", agent_name="child-model", entry_point="web",
    )
    monkeypatch.setenv("DAGI_API_KEY", "RUNTIME_CONTEXT_MUST_NOT_COPY_ENV")

    events = list(agent.run_turn("Inspect the assigned child workspace.", run_id=child_run))

    assert events[-1].status == "completed"
    first = _runtime_context(provider.requests[0])
    second = _runtime_context(provider.requests[1])
    assert first["identity"] == {
        "agent_id": "child-agent", "agent_name": "child-model",
        "session_id": child_session, "run_id": child_run,
        "parent_session_id": parent_session, "parent_run_id": parent_run, "role": "child",
    }
    assert first["environment"]["entry_point"] == "web"
    assert first["environment"]["workspace"] == ".dagi-children/child-17"
    assert first["environment"]["resolved_workspace"] == str(child_workspace)
    assert first["environment"]["shell_enabled"] is False
    assert "read_file" in first["environment"]["enabled_tools"]
    assert "run_bash" not in first["environment"]["enabled_tools"]
    assert first["assignment"]["purpose"] is None
    assert first["assignment"]["required_output"] is None
    assert first["assignment"]["trust"] == "untrusted"
    assert first["limits"]["remaining_provider_calls"] == 4
    assert second["limits"]["remaining_provider_calls"] == 3
    assert first["limits"]["cost_status"] == "not_configured"
    assert first["progress"]["phase"] == "provider_request"
    serialized = json.dumps(first, ensure_ascii=False)
    assert "UNRELATED_SESSION_SECRET" not in serialized
    assert "RUNTIME_CONTEXT_MUST_NOT_COPY_ENV" not in serialized
    assert len(serialized.encode("utf-8")) <= 4_000
    state.close()


def test_root_request_identifies_cli_and_legacy_root_workspace(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session("root")
    provider = CapturingProvider([
        [StreamEvent(kind="text", text="Ready."), StreamEvent(kind="finish", finish_reason="stop")],
    ])
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    agent = Agent(provider, tools, state, session, entry_point="cli")

    events = list(agent.run_turn("Say ready."))

    assert events[-1].status == "completed"
    context = _runtime_context(provider.requests[0])
    assert context["identity"]["role"] == "root"
    assert context["identity"]["parent_session_id"] is None
    assert context["identity"]["parent_run_id"] is None
    assert context["environment"]["entry_point"] == "cli"
    assert context["environment"]["workspace"] == "."
    assert context["assignment"]["purpose"] is None
    assert context["assignment"]["required_output"] is None
    state.close()
