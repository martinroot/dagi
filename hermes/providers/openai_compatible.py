"""Minimal adapter for OpenAI-compatible chat-completion APIs."""

from __future__ import annotations

import json
from typing import Any, Iterator

from openai import OpenAI

from .base import LLMProvider, Message, StreamChunk, ToolCall, ToolSpec


def _to_openai_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        if message.role == "user":
            result.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in message.tool_calls
                ]
            result.append(entry)
        elif message.role == "tool":
            for tool_result in message.tool_results:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_result.tool_call_id,
                        "content": tool_result.content,
                    }
                )
    return result


def _to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


class OpenAICompatibleProvider(LLMProvider):
    """Stream text and complete function calls from a compatible API endpoint."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(model, api_key)
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._extra_headers = extra_headers or {}

    def stream(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Iterator[StreamChunk]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=_to_openai_messages(system, messages),
            tools=_to_openai_tools(tools) if tools else None,
            stream=True,
            stream_options={"include_usage": True},
            extra_headers=self._extra_headers or None,
        )
        pending: dict[int, dict[str, str | None]] = {}

        for chunk in response:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                yield StreamChunk(
                    kind="usage",
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                )
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield StreamChunk(kind="text_delta", text=delta.content)
            for call_delta in delta.tool_calls or []:
                partial = pending.setdefault(
                    call_delta.index, {"id": None, "name": "", "arguments": ""}
                )
                if call_delta.id:
                    partial["id"] = call_delta.id
                if call_delta.function and call_delta.function.name:
                    partial["name"] = (partial["name"] or "") + call_delta.function.name
                if call_delta.function and call_delta.function.arguments:
                    partial["arguments"] = (partial["arguments"] or "") + call_delta.function.arguments

        for index in sorted(pending):
            partial = pending[index]
            if not partial["id"] or not partial["name"]:
                raise ValueError(f"Incomplete streamed tool call at index {index}")
            try:
                arguments = json.loads(partial["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON arguments for tool {partial['name']!r}") from exc
            if not isinstance(arguments, dict):
                raise ValueError(f"Tool arguments for {partial['name']!r} must be a JSON object")
            yield StreamChunk(
                kind="tool_call",
                tool_call=ToolCall(
                    id=partial["id"], name=partial["name"], arguments=arguments
                ),
            )

        yield StreamChunk(kind="done")
