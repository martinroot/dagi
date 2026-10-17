from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Thread

from dagi_core.agent import Agent
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import ToolExecutionContext, ToolRegistry
from dagi_core.usage import UsagePolicy
from dagi_core.delegation import DelegationManager


class ScriptedProvider:
    def __init__(self, model, responses):
        self.model = model
        self.responses = list(responses)
        self.requests = []

    def stream(self, messages, tools):
        self.requests.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return iter(response)


def _usage(input_tokens=20, output_tokens=5):
    return StreamEvent(kind="usage", usage={"input_tokens": input_tokens, "output_tokens": output_tokens})


def _parent_responses():
    return [
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "delegate-1", "name": "delegate_task",
                "arguments": {
                    "task": "Calculate the requested result.",
                    "model": "child-model",
                    "context": "Only transfer this approved fact.",
                },
            }),
            _usage(),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [
            StreamEvent(kind="text", text="I checked the child result."),
            _usage(),
            StreamEvent(kind="finish", finish_reason="stop"),
        ],
    ]


def _manager(state, workspace, factory, *, depth=2, children=3):
    return DelegationManager(
        state,
        workspace,
        api_key="fake-key",
        base_url="https://api.example/v1",
        provider_factory=factory,
        compression_model="summary-model",
        usage_policy=UsagePolicy(max_calls_per_run=12),
        max_depth=depth,
        max_children=children,
    )


def test_parent_delegates_with_explicit_context_and_checks_child_result(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    parent_session = state.create_session("parent")
    state.append_message(parent_session, {"role": "user", "content": "PRIVATE_PARENT_NOT_TRANSFERRED"})
    parent_provider = ScriptedProvider("parent-model", _parent_responses())
    child_provider = ScriptedProvider("child-model", [
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "child-memory-1", "name": "search_memory",
                "arguments": {"query": "PRIVATE_PARENT_NOT_TRANSFERRED"},
            }),
            _usage(8, 2),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [
            StreamEvent(kind="text", text="The answer is 42."),
            _usage(12, 4),
            StreamEvent(kind="finish", finish_reason="stop"),
        ],
    ])
    providers = {
        "parent-model": parent_provider, "child-model": child_provider,
        "summary-model": ScriptedProvider("summary-model", []),
    }

    def factory(model, _key, _base_url):
        return providers[model]

    tools = ToolRegistry(tmp_path / "workspace", state, parent_session)
    manager = _manager(state, tmp_path / "workspace", factory)
    manager.register(tools)
    parent = Agent(parent_provider, tools, state, parent_session, usage_policy=UsagePolicy(max_calls_per_run=12))

    events = list(parent.run_turn("delegate this"))

    child_sessions = [item for item in state.list_sessions(100) if item["title"].startswith("Child:")]
    assert len(child_sessions) == 1
    child_session = child_sessions[0]["id"]
    child_run = state.list_runs(child_session)[0]
    child_session_record = state.get_session(child_session)
    assert child_session_record is not None
    assert child_session_record["parent_id"] == parent_session
    assert child_session_record["workspace"].startswith(".dagi-children/")
    child_workspace = (tmp_path / "workspace" / child_session_record["workspace"]).resolve()
    assert child_workspace.is_dir()
    parent_run_id = events[-1].run_id
    assert parent_run_id is not None
    assert child_run["parent_run_id"] == parent_run_id
    assert child_run["depth"] == 1
    assert child_run["agent_name"] == "child-model"
    parent_record = state.get_run(parent_run_id)
    assert parent_record is not None and child_run["agent_id"] != parent_record["agent_id"]
    child_messages = state.messages(child_session)
    assert "Only transfer this approved fact." in child_messages[0]["content"]
    assert "PRIVATE_PARENT_NOT_TRANSFERRED" not in child_messages[0]["content"]
    memory_result = next(message for message in child_messages if message.get("tool_call_id") == "child-memory-1")
    assert memory_result["content"] == "(no matches)"
    assert "PRIVATE_PARENT_NOT_TRANSFERRED" not in memory_result["content"]
    assert "(no matches)" in str(child_provider.requests[1]["messages"])
    parent_tool_result = next(message for message in state.messages(parent_session) if message.get("tool_call_id") == "delegate-1")
    assert "The answer is 42." in parent_tool_result["content"]
    assert "The answer is 42." in str(parent_provider.requests[1]["messages"])
    delegation_result = next(
        event for event in events if event.kind == "tool_result" and event.tool_call_id == "delegate-1"
    )
    assert delegation_result.presentation is not None
    assert delegation_result.presentation["type"] == "delegation"
    child_artifact = delegation_result.presentation["artifacts"][0]
    assert child_artifact["child_session_id"] == child_session
    assert child_artifact["child_run_id"] == child_run["run_id"]
    assert child_artifact["parent_run_id"] == parent_run_id
    assert child_artifact["task"] == "Calculate the requested result."
    assert child_artifact["model"] == "child-model"
    assert child_artifact["status"] == "completed"
    assert child_artifact["workspace"] == child_session_record["workspace"]
    child_inbox = state.inbox(parent_session)
    assert child_inbox[0]["child_session_id"] == child_session
    assert child_inbox[0]["run_id"] == child_run["run_id"]
    assert child_inbox[0]["result"] == "The answer is 42."
    assert state.usage_summary_for_budget(parent_run_id)["provider_calls"] == 4
    assert state.list_provider_calls(child_run["run_id"])[0]["model"] == "child-model"
    state.close()


def test_child_failure_is_returned_to_parent_as_structured_error(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session("parent")
    parent_provider = ScriptedProvider("parent-model", _parent_responses())
    child_provider = ScriptedProvider("child-model", [RuntimeError("child provider failed")])
    providers = {
        "parent-model": parent_provider, "child-model": child_provider,
        "summary-model": ScriptedProvider("summary-model", []),
    }
    manager = _manager(state, tmp_path / "workspace", lambda model, *_args: providers[model])
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    manager.register(tools)

    events = list(Agent(parent_provider, tools, state, session).run_turn("delegate"))

    assert any(event.kind == "tool_result" and event.is_error is True for event in events)
    assert any("child provider failed" in str(message.get("content")) for message in parent_provider.requests[1]["messages"])
    child_sessions = [item for item in state.list_sessions(100) if item["title"].startswith("Child:")]
    child_run = state.list_runs(child_sessions[0]["id"])[0]
    assert child_run["status"] == "error"
    state.close()


def test_parent_cancellation_reaches_an_active_child_provider(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session("parent")
    parent_provider = ScriptedProvider("parent-model", _parent_responses())
    cancel = Event()
    child_started = Event()

    class BlockingProvider:
        model = "child-model"

        def __init__(self):
            self.cancelled = Event()

        def stream(self, *_args):
            child_started.set()
            self.cancelled.wait(timeout=5)
            if self.cancelled.is_set():
                raise RuntimeError("child stream closed")
            yield StreamEvent(kind="finish", finish_reason="stop")

        def cancel(self):
            self.cancelled.set()

    child_provider = BlockingProvider()
    providers = {
        "parent-model": parent_provider, "child-model": child_provider,
        "summary-model": ScriptedProvider("summary-model", []),
    }
    manager = _manager(state, tmp_path / "workspace", lambda model, *_args: providers[model])
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    manager.register(tools)
    registered = []

    def request_cancel():
        assert child_started.wait(timeout=3)
        cancel.set()
        for provider in registered:
            cancel_provider = getattr(provider, "cancel", None)
            if callable(cancel_provider):
                cancel_provider()

    thread = Thread(target=request_cancel)
    thread.start()
    events = list(Agent(parent_provider, tools, state, session).run_turn(
        "delegate", cancel_event=cancel, register_provider=registered.append,
    ))
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert events[-1].status == "cancelled"
    child_sessions = [item for item in state.list_sessions(100) if item["title"].startswith("Child:")]
    assert state.list_runs(child_sessions[0]["id"])[0]["status"] == "cancelled"
    state.close()


def test_child_cannot_delegate_beyond_the_configured_depth(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session("parent")
    parent_provider = ScriptedProvider("parent-model", _parent_responses())
    child_provider = ScriptedProvider("child-model", [
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "delegate-2", "name": "delegate_task",
                "arguments": {"task": "recurse forever", "model": "child-model"},
            }),
            _usage(),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [
            StreamEvent(kind="text", text="The depth guard stopped recursion."),
            _usage(),
            StreamEvent(kind="finish", finish_reason="stop"),
        ],
    ])
    providers = {
        "parent-model": parent_provider, "child-model": child_provider,
        "summary-model": ScriptedProvider("summary-model", []),
    }
    manager = _manager(state, tmp_path / "workspace", lambda model, *_args: providers[model], depth=1)
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    manager.register(tools)

    events = list(Agent(parent_provider, tools, state, session).run_turn("delegate"))

    assert events[-1].status == "completed"
    assert len([item for item in state.list_sessions(100) if item["title"].startswith("Child:")]) == 1
    assert state.count_child_runs_in_budget_group(events[-1].run_id) == 1
    assert len(child_provider.requests) == 2
    assert "depth limit reached" in str(child_provider.requests[1]["messages"])
    state.close()


def test_provider_setup_failure_marks_the_child_run_as_error(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session("parent")
    parent_provider = ScriptedProvider("parent-model", _parent_responses())

    def factory(model, *_args):
        if model == "parent-model":
            return parent_provider
        raise RuntimeError("child provider factory failed")

    manager = _manager(state, tmp_path / "workspace", factory)
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    manager.register(tools)
    list(Agent(parent_provider, tools, state, session).run_turn("delegate"))

    child = [item for item in state.list_sessions(100) if item["title"].startswith("Child:")][0]
    child_run = state.list_runs(child["id"])[0]
    assert child_run["status"] == "error"
    assert "child provider factory failed" in child_run["error"]
    state.close()


def test_parent_and_child_share_the_provider_call_budget(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session("parent")
    parent_provider = ScriptedProvider("parent-model", _parent_responses())
    child_provider = ScriptedProvider("child-model", [[
        StreamEvent(kind="text", text="child done"),
        _usage(),
        StreamEvent(kind="finish", finish_reason="stop"),
    ]])
    providers = {
        "parent-model": parent_provider, "child-model": child_provider,
        "summary-model": ScriptedProvider("summary-model", []),
    }
    policy = UsagePolicy(max_calls_per_run=2)
    factory = lambda model, *_args: providers[model]
    manager = DelegationManager(
        state, tmp_path / "workspace", api_key="fake-key", base_url="https://api.example/v1",
        provider_factory=factory, compression_model="summary-model", usage_policy=policy,
    )
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    manager.register(tools)
    events = list(Agent(parent_provider, tools, state, session, usage_policy=policy).run_turn("delegate"))
    run_id = events[-1].run_id

    assert events[-1].status == "limit"
    assert len(parent_provider.requests) == 1
    assert state.usage_summary_for_budget(run_id)["provider_calls"] == 2
    state.close()


def test_delegation_enforces_depth_and_total_child_limit(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session("parent")
    parent_run = state.create_run(session)
    factory = lambda *_args: ScriptedProvider("unused", [])
    workspace = tmp_path / "workspace"

    depth_tools = ToolRegistry(workspace, state, session)
    depth_manager = _manager(state, workspace, factory, depth=1, children=4)
    depth_manager.register(depth_tools)
    depth_tools.set_execution_context(ToolExecutionContext(session, parent_run, 1, "parent-model"))
    too_deep = depth_tools.call("delegate_task", {"task": "never start", "model": "child-model"})
    assert too_deep.is_error is True
    assert state.count_child_runs_in_budget_group(parent_run) == 0

    child_session = state.create_session("already created", parent_id=session)
    state.create_run(child_session, parent_run_id=parent_run, agent_name="existing-child")
    count_tools = ToolRegistry(workspace, state, session)
    count_manager = _manager(state, workspace, factory, depth=3, children=1)
    count_manager.register(count_tools)
    count_tools.set_execution_context(ToolExecutionContext(session, parent_run, 0, "parent-model"))
    too_many = count_tools.call("delegate_task", {"task": "do not start", "model": "child-model"})
    assert too_many.is_error is True
    assert state.count_child_runs_in_budget_group(parent_run) == 1
    state.close()


def test_delegation_assignment_contract_survives_child_resume(tmp_path):
    root = tmp_path / "workspace"
    state = StateStore(tmp_path / "state.sqlite3")
    parent_session = state.create_session("parent")
    task_text = "Validate the dataset; literal DAGI_ASSIGNMENT_CONTRACT_JSON_BEGIN is task data."
    parent_provider = ScriptedProvider("parent-model", [
        [
            StreamEvent(kind="tool_call", tool_call={
                "id": "delegate-contract", "name": "delegate_task",
                "arguments": {
                    "task": task_text,
                    "model": "child-model",
                    "context": "Approved source file is input.json.",
                    "purpose": "The parent needs valid data before producing its report.",
                    "required_output": "validated.json",
                    "acceptance_check_ids": ["check-7"],
                },
            }),
            _usage(),
            StreamEvent(kind="finish", finish_reason="tool_calls"),
        ],
        [StreamEvent(kind="text", text="The child result is ready."), _usage(), StreamEvent(kind="finish", finish_reason="stop")],
    ])
    child_provider = ScriptedProvider("child-model", [
        [StreamEvent(kind="text", text="Dataset validated."), _usage(), StreamEvent(kind="finish", finish_reason="stop")],
    ])
    providers = {
        "parent-model": parent_provider,
        "child-model": child_provider,
        "summary-model": ScriptedProvider("summary-model", []),
    }
    policy = UsagePolicy(max_calls_per_run=8)
    factory = lambda model, *_args: providers[model]
    manager = DelegationManager(
        state, root, api_key="fake-key", base_url="https://api.example/v1",
        provider_factory=factory, compression_model="summary-model", usage_policy=policy,
    )
    parent_tools = ToolRegistry(root, state, parent_session)
    manager.register(parent_tools)
    parent = Agent(
        parent_provider, parent_tools, state, parent_session,
        usage_policy=policy, entry_point="web",
    )

    events = list(parent.run_turn("Delegate dataset validation."))

    assert events[-1].status == "completed"
    delegate_spec = next(
        item["function"] for item in parent_provider.requests[0]["tools"]
        if item["function"]["name"] == "delegate_task"
    )
    assert {"purpose", "required_output", "acceptance_check_ids"} <= set(delegate_spec["parameters"]["properties"])
    child = next(item for item in state.list_sessions(100) if item["parent_id"] == parent_session)
    first_user_message = next(message for message in state.messages(child["id"]) if message["role"] == "user")
    assert "DAGI_ASSIGNMENT_CONTRACT_JSON_BEGIN" in first_user_message["content"]

    def request_context(provider_request):
        system = provider_request["messages"][0]["content"]
        start = system.index("DAGI_RUNTIME_CONTEXT_JSON_BEGIN\n") + len("DAGI_RUNTIME_CONTEXT_JSON_BEGIN\n")
        end = system.index("\nDAGI_RUNTIME_CONTEXT_JSON_END", start)
        return json.loads(system[start:end])

    initial_context = request_context(child_provider.requests[0])
    assert initial_context["assignment"]["my_task"] == task_text
    assert initial_context["assignment"]["purpose"] == "The parent needs valid data before producing its report."
    assert initial_context["assignment"]["required_output"] == "validated.json"
    assert initial_context["assignment"]["acceptance_check_ids"] == ["check-7"]
    assert initial_context["assignment"]["trust"] == "untrusted"

    child_record = state.get_session(child["id"])
    assert child_record is not None
    child_workspace = (root / child_record["workspace"]).resolve()
    resume_provider = ScriptedProvider("child-model", [[
        StreamEvent(kind="text", text="Resumed with the saved assignment."),
        _usage(),
        StreamEvent(kind="finish", finish_reason="stop"),
    ]])
    resumed_tools = ToolRegistry(child_workspace, state, child["id"])
    resumed_agent = Agent(
        resume_provider, resumed_tools, state, child["id"],
        usage_policy=policy, agent_name="child-model", entry_point="web",
    )
    resumed_events = list(resumed_agent.run_turn("Continue validation."))
    resumed_context = request_context(resume_provider.requests[0])
    assert resumed_events[-1].status == "completed"
    assert resumed_context["assignment"]["purpose"] == initial_context["assignment"]["purpose"]
    assert resumed_context["assignment"]["required_output"] == "validated.json"
    state.close()
