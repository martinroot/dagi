from copy import deepcopy

import pytest

from dagi_core.agent import Agent
from dagi_core.context import ContextBuilder, ContextLimitError
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import ToolRegistry
from dagi_core.usage import UsagePolicy


class FakeCompressor:
    model = "summary-model"

    def __init__(self):
        self.requests = []

    def stream(self, messages, tools):
        self.requests.append({
            "model": self.model, "messages": deepcopy(messages), "tools": deepcopy(tools),
            "stream": True, "stream_options": {"include_usage": True},
        })
        return iter([
            StreamEvent(kind="text", text="COMPACT SUMMARY"),
            StreamEvent(kind="usage", usage={"input_tokens": 80, "output_tokens": 4}),
            StreamEvent(kind="finish", finish_reason="stop"),
        ])


class RecordingProvider:
    model = "main-model"

    def __init__(self):
        self.requests = []

    def stream(self, messages, tools):
        self.requests.append({
            "model": self.model, "messages": deepcopy(messages), "tools": deepcopy(tools),
            "stream": True, "stream_options": {"include_usage": True},
        })
        return iter([
            StreamEvent(kind="text", text="Done"),
            StreamEvent(kind="finish", finish_reason="stop"),
        ])


def _append_tool_pair(state, session, call_id, content):
    state.append_message(session, {"role": "user", "content": "inspect the file"})
    state.append_message(session, {
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": call_id, "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"notes.txt"}'},
        }],
    })
    state.append_message(session, {
        "role": "tool", "tool_call_id": call_id, "name": "read_file", "content": content,
    })
    state.append_message(session, {"role": "assistant", "content": "The file is readable."})


def test_context_builder_truncates_tool_output_without_changing_source(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    _append_tool_pair(state, session, "call-large", "x" * 500)
    run = state.create_run(session)
    builder = ContextBuilder(state, max_tokens=2_000, max_tool_result_chars=24)

    messages = builder.build(session, run, "system", [])

    tool_message = next(item for item in messages if item["role"] == "tool")
    original = next(item for item in state.messages(session) if item.get("tool_call_id") == "call-large")
    assert len(tool_message["content"]) < 100
    assert "truncated" in tool_message["content"]
    assert len(original["content"]) == 500
    state.close()


def test_context_compresses_old_turns_preserves_sources_and_keeps_tool_pairs(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    old_user = state.append_message(session, {"role": "user", "content": "old question " + "a" * 900})
    old_answer = state.append_message(session, {"role": "assistant", "content": "old answer " + "b" * 900})
    _append_tool_pair(state, session, "recent-call", "current file result")
    state.append_message(session, {"role": "user", "content": "continue with the next step"})
    run = state.create_run(session)
    compressor = FakeCompressor()
    builder = ContextBuilder(
        state, max_tokens=350, max_tool_result_chars=200,
        compression_provider=compressor, usage_policy=UsagePolicy(),
    )
    original_count = len(state.messages(session))

    messages = builder.build(session, run, "system prompt", [{"name": "read_file"}])

    assert any("COMPACT SUMMARY" in item.get("content", "") for item in messages)
    call_ids = {
        call["id"]
        for item in messages if item.get("tool_calls")
        for call in item["tool_calls"]
    }
    result_ids = {item["tool_call_id"] for item in messages if item["role"] == "tool"}
    assert call_ids == result_ids == {"recent-call"}
    assert len(state.messages(session)) == original_count
    archive = state.list_context_archives(session)[-1]
    assert set(archive["source_message_ids"]) == {old_user, old_answer}
    compression_call = next(call for call in state.list_provider_calls(run) if call["purpose"] == "context_compression")
    assert compression_call["model"] == "summary-model"
    assert state.get_provider_request(compression_call["id"]) == compressor.requests[0]
    assert state.usage_summary(run)["provider_calls"] == 1
    state.close()


def test_single_oversized_current_turn_fails_instead_of_silently_exceeding_limit(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    state.append_message(session, {"role": "user", "content": "important " * 500})
    run = state.create_run(session)
    builder = ContextBuilder(state, max_tokens=40, max_tool_result_chars=20)

    with pytest.raises(ContextLimitError, match="context limit"):
        builder.build(session, run, "system", [])
    state.close()


def test_agent_persists_exact_request_sent_to_main_provider(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    provider = RecordingProvider()
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    builder = ContextBuilder(state, max_tokens=10_000, max_tool_result_chars=100)

    events = list(Agent(provider, tools, state, session, context_builder=builder).run_turn("hello"))

    provider_call = state.list_provider_calls(events[-1].run_id)[0]
    assert provider_call["purpose"] == "agent"
    assert state.get_provider_request(provider_call["id"]) == provider.requests[0]
    state.close()
