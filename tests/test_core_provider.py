from types import SimpleNamespace as NS

from dagi_core.provider import OpenAICompatibleProvider, StreamEvent


def test_provider_streams_text_and_reassembles_function_call():
    text = NS(choices=[NS(delta=NS(content="Ready", tool_calls=None))], usage=None)
    first_tool_piece = NS(
        choices=[NS(delta=NS(content=None, tool_calls=[NS(index=0, id="call-1", function=NS(name="write_", arguments='{"path":'))]))],
        usage=None,
    )
    second_tool_piece = NS(
        choices=[NS(delta=NS(content=None, tool_calls=[NS(index=0, id=None, function=NS(name="file", arguments='"a.txt","content":"ok"}'))]))],
        usage=None,
    )

    class Completions:
        kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return iter([text, first_tool_piece, second_tool_piece])

    completions = Completions()
    provider = OpenAICompatibleProvider("test-model", "fake-key", "https://api.example/v1")
    provider._client = NS(chat=NS(completions=completions))
    tools = [{"type": "function", "function": {"name": "write_file", "parameters": {"type": "object"}}}]
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "write"}]

    events = list(provider.stream(messages, tools))

    assert events[0] == StreamEvent(kind="text", text="Ready")
    assert events[1] == StreamEvent(
        kind="tool_call", tool_call={"id": "call-1", "name": "write_file", "arguments": {"path": "a.txt", "content": "ok"}}
    )
    assert completions.kwargs["model"] == "test-model"
    assert completions.kwargs["messages"] == messages
    assert completions.kwargs["stream"] is True


def test_provider_refuses_malformed_tool_arguments():
    chunk = NS(
        choices=[NS(delta=NS(content=None, tool_calls=[NS(index=0, id="bad", function=NS(name="write_file", arguments="{"))]))],
        usage=None,
    )

    class Completions:
        def create(self, **_kwargs):
            return iter([chunk])

    provider = OpenAICompatibleProvider("test", "fake-key")
    provider._client = NS(chat=NS(completions=Completions()))

    try:
        list(provider.stream([], []))
    except ValueError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("provider accepted malformed tool arguments")
