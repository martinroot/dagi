"""Single OpenAI-compatible streaming adapter for the minimal core."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator, Literal

from openai import OpenAI


@dataclass(frozen=True)
class StreamEvent:
    kind: Literal["text", "tool_call", "usage", "finish"]
    text: str | None = None
    tool_call: dict[str, Any] | None = None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None


class IncompleteStreamError(ValueError):
    """The provider stream ended without a valid terminal chunk."""


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
            stream_options={"include_usage": True},
        )
        pending: dict[int, dict[str, str | None]] = {}
        finish_reason: str | None = None
        actual_usage: dict[str, int] | None = None
        try:
            for chunk in response:
                usage = getattr(chunk, "usage", None)
                input_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
                output_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
                if (
                    isinstance(input_tokens, int) and not isinstance(input_tokens, bool) and input_tokens >= 0
                    and isinstance(output_tokens, int) and not isinstance(output_tokens, bool) and output_tokens >= 0
                ):
                    actual_usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    yield StreamEvent(kind="text", text=delta.content)
                for call in (delta.tool_calls if delta else None) or []:
                    partial = pending.setdefault(
                        call.index, {"id": None, "name": "", "arguments": ""}
                    )
                    if call.id:
                        partial["id"] = call.id
                    if call.function and call.function.name:
                        partial["name"] = (partial["name"] or "") + call.function.name
                    if call.function and call.function.arguments:
                        partial["arguments"] = (partial["arguments"] or "") + call.function.arguments
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason

            if actual_usage is not None:
                yield StreamEvent(kind="usage", usage=actual_usage)
            if finish_reason is None:
                raise IncompleteStreamError("provider stream ended before finish_reason")
            if finish_reason not in {"stop", "tool_calls", "length", "content_filter"}:
                raise IncompleteStreamError(f"unsupported finish_reason: {finish_reason!r}")

            completed_calls: list[dict[str, Any]] = []
            if finish_reason == "tool_calls":
                if not pending:
                    raise IncompleteStreamError("finish_reason was tool_calls but no calls arrived")
                for index in sorted(pending):
                    partial = pending[index]
                    if not partial["id"] or not partial["name"]:
                        raise IncompleteStreamError(f"incomplete streamed tool call at index {index}")
                    name = partial["name"]
                    try:
                        arguments = json.loads(partial["arguments"] or "{}")
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"invalid JSON arguments for {name!r}") from exc
                    if not isinstance(arguments, dict):
                        raise ValueError(f"tool arguments for {name!r} must be a JSON object")
                    completed_calls.append({"id": partial["id"], "name": name, "arguments": arguments})
            elif pending and finish_reason == "stop":
                raise IncompleteStreamError("tool calls arrived with a non-tool finish_reason")

            # Expose calls only after the complete response has validated as a tool round.
            for call in completed_calls:
                yield StreamEvent(kind="tool_call", tool_call=call)
            yield StreamEvent(kind="finish", finish_reason=finish_reason)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
