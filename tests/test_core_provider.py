from types import SimpleNamespace as NS

import pytest

from dagi_core.provider import OpenAICompatibleProvider, StreamEvent


def _chunk(*, content=None, tool_calls=None, finish_reason=None, usage=None):
    return NS(
        choices=[NS(
            delta=NS(content=content, tool_calls=tool_calls),
            finish_reason=finish_reason,
        )],
        usage=usage,
    )


def _tool_piece(index, call_id, name, arguments):
    return NS(index=index, id=call_id, function=NS(name=name, arguments=arguments))


def _provider_for(response):
    class Completions:
        kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return response

    completions = Completions()
    provider = OpenAICompatibleProvider("test-model", "fake-key", "https://api.example/v1")
    provider._client = NS(chat=NS(completions=completions))
    return provider, completions


def test_provider_reassembles_fragmented_arguments_and_multiple_calls():
    chunks = iter([
        _chunk(content="Ready"),
        _chunk(tool_calls=[_tool_piece(0, "call-1", "write_", '{"path":')]),
        _chunk(tool_calls=[_tool_piece(0, None, "file", '"a.txt","content":"ok"}')]),
        _chunk(tool_calls=[_tool_piece(1, "call-2", "list_dir", '{"path":')]),
        _chunk(tool_calls=[_tool_piece(1, None, None, '"."}')]),
        _chunk(finish_reason="tool_calls"),
    ])
    provider, completions = _provider_for(chunks)
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "write"}]
    tools = [{"type": "function", "function": {"name": "write_file", "parameters": {"type": "object"}}}]

    events = list(provider.stream(messages, tools))

    assert events == [
        StreamEvent(kind="text", text="Ready"),
        StreamEvent(kind="tool_call", tool_call={"id": "call-1", "name": "write_file", "arguments": {"path": "a.txt", "content": "ok"}}),
        StreamEvent(kind="tool_call", tool_call={"id": "call-2", "name": "list_dir", "arguments": {"path": "."}}),
        StreamEvent(kind="finish", finish_reason="tool_calls"),
    ]
    assert completions.kwargs["model"] == "test-model"
    assert completions.kwargs["messages"] == messages
    assert completions.kwargs["stream"] is True


def test_filtered_response_discards_pending_tool_calls():
    response = iter([
        _chunk(tool_calls=[_tool_piece(0, "call-1", "write_file", '{"path":"blocked"}')]),
        _chunk(finish_reason="content_filter"),
    ])
    provider, _ = _provider_for(response)

    events = list(provider.stream([], []))

    assert events == [StreamEvent(kind="finish", finish_reason="content_filter")]


def test_actual_usage_survives_an_incomplete_stream():
    response = iter([
        _chunk(content="partial"),
        NS(choices=[], usage=NS(prompt_tokens=10, completion_tokens=2)),
    ])
    provider, _ = _provider_for(response)
    events = []

    with pytest.raises(ValueError, match="finish"):
        events.extend(provider.stream([], []))

    assert StreamEvent(kind="usage", usage={"input_tokens": 10, "output_tokens": 2}) in events


def test_provider_rejects_stream_without_finish_reason():
    provider, _ = _provider_for(iter([_chunk(content="partial")]))

    with pytest.raises(ValueError, match="finish"):
        list(provider.stream([], []))


class _ClosableResponse:
    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self):
        self.closed = True


def test_provider_closes_transport_when_stream_is_cancelled():
    response = _ClosableResponse([_chunk(content="partial")])
    provider, _ = _provider_for(response)
    stream = provider.stream([], [])

    assert next(stream) == StreamEvent(kind="text", text="partial")
    stream.close()

    assert response.closed is True


def test_provider_cancel_closes_the_active_transport():
    response = _ClosableResponse([_chunk(content="partial")])
    provider, _ = _provider_for(response)
    stream = provider.stream([], [])

    assert next(stream) == StreamEvent(kind="text", text="partial")
    provider.cancel()

    assert response.closed is True
    stream.close()


def test_provider_requests_and_forwards_usage_data():
    response = iter([
        _chunk(finish_reason="stop"),
        NS(choices=[], usage=NS(prompt_tokens=17, completion_tokens=5)),
    ])
    provider, completions = _provider_for(response)

    events = list(provider.stream([], []))

    assert events == [
        StreamEvent(kind="usage", usage={"input_tokens": 17, "output_tokens": 5}),
        StreamEvent(kind="finish", finish_reason="stop"),
    ]
    assert completions.kwargs["stream_options"] == {"include_usage": True}


def test_provider_refuses_malformed_tool_arguments():
    response = iter([
        _chunk(tool_calls=[_tool_piece(0, "bad", "write_file", "{")]),
        _chunk(finish_reason="tool_calls"),
    ])
    provider, _ = _provider_for(response)

    with pytest.raises(ValueError, match="invalid JSON"):
        list(provider.stream([], []))
