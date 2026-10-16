"""Single OpenAI-compatible streaming adapter for the minimal core."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator, Literal

from openai import OpenAI


@dataclass(frozen=True)
class StreamEvent:
    kind: Literal["text", "tool_call"]
    text: str | None = None
    tool_call: dict[str, Any] | None = None


class OpenAICompatibleProvider:
    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[StreamEvent]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or None,
            stream=True,
        )
        pending: dict[int, dict[str, str | None]] = {}
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield StreamEvent(kind="text", text=delta.content)
            for call in delta.tool_calls or []:
                partial = pending.setdefault(
                    call.index, {"id": None, "name": "", "arguments": ""}
                )
                if call.id:
                    partial["id"] = call.id
                if call.function and call.function.name:
                    partial["name"] = (partial["name"] or "") + call.function.name
                if call.function and call.function.arguments:
                    partial["arguments"] = (partial["arguments"] or "") + call.function.arguments

        for index in sorted(pending):
            partial = pending[index]
            if not partial["id"] or not partial["name"]:
                raise ValueError(f"incomplete streamed tool call at index {index}")
            try:
                arguments = json.loads(partial["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON arguments for {partial['name']!r}") from exc
            if not isinstance(arguments, dict):
                raise ValueError(f"tool arguments for {partial['name']!r} must be a JSON object")
            yield StreamEvent(
                kind="tool_call",
                tool_call={"id": partial["id"], "name": partial["name"], "arguments": arguments},
            )
