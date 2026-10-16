from types import SimpleNamespace

from hermes.providers.base import Message, ToolCall, ToolResult, ToolSpec
from hermes.providers.openai_compatible import OpenAICompatibleProvider, _to_openai_messages


def test_openai_message_conversion_preserves_tool_cycle():
    messages = [
        Message(role="user", content="write a note"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="call-1", name="write_file", arguments={"path": "n.txt"})],
        ),
        Message(
            role="tool",
            tool_results=[ToolResult("call-1", "write_file", "wrote file")],
        ),
    ]

    converted = _to_openai_messages("system prompt", messages)

    assert converted == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "write a note"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "write_file", "arguments": '{"path": "n.txt"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "wrote file"},
    ]


def test_stream_adapter_reassembles_text_tool_calls_and_usage():
    text_chunk = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello", tool_calls=None))],
        usage=None,
    )
    tool_chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id="call-2",
                            function=SimpleNamespace(
                                name="write_file", arguments='{"path":"x.txt","content":"ok"}'
                            ),
                        )
                    ],
                )
            )
        ],
        usage=None,
    )
    usage_chunk = SimpleNamespace(
        choices=[], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2)
    )

    class FakeCompletions:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return iter([text_chunk, tool_chunk, usage_chunk])

    completions = FakeCompletions()
    provider = OpenAICompatibleProvider("test-model", "not-a-real-key")
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    tools = [ToolSpec("write_file", "write a file", {"type": "object"})]

    chunks = list(provider.stream("system", [Message("user", "do it")], tools))

    assert [chunk.kind for chunk in chunks] == ["text_delta", "usage", "tool_call", "done"]
    assert chunks[0].text == "Hello"
    assert chunks[1].input_tokens == 3 and chunks[1].output_tokens == 2
    assert chunks[2].tool_call == ToolCall(
        id="call-2", name="write_file", arguments={"path": "x.txt", "content": "ok"}
    )
    assert completions.kwargs["model"] == "test-model"
    assert completions.kwargs["tools"][0]["function"]["name"] == "write_file"
    assert completions.kwargs["stream"] is True
