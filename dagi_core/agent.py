"""The minimal Hermes-style loop: model response, tool round, durable transcript."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator, Literal

from .provider import IncompleteStreamError, OpenAICompatibleProvider
from .state import StateStore
from .tools import ToolError, ToolRegistry

MAX_TOOL_ROUNDS = 16
SYSTEM_PROMPT = """You are Dagi, a minimal Hermes-style agent running in a terminal.
Use tools only when they help complete the user's request. File tools are confined to the
configured workspace. Shell is not available unless explicitly enabled; when enabled, the
user must approve every command. The workspace is not an operating-system sandbox.
Use search_memory to recall prior work. Use saved skills when relevant and create a skill
when you have discovered a reusable procedure. Be honest about tool results; never invent them."""


@dataclass(frozen=True)
class AgentEvent:
    kind: Literal["text", "tool_call", "tool_result", "error", "done"]
    session_id: int | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    status: str | None = None


class Agent:
    def __init__(
        self,
        provider: OpenAICompatibleProvider,
        tools: ToolRegistry,
        state: StateStore,
        session_id: int,
        system_prompt: str = SYSTEM_PROMPT,
    ):
        self.provider = provider
        self.tools = tools
        self.state = state
        self.session_id = session_id
        self.system_prompt = system_prompt

    def run_turn(self, user_text: str) -> Iterator[AgentEvent]:
        if not user_text.strip():
            raise ValueError("user message must not be empty")
        run_id = self.state.create_run(self.session_id)
        status = "running"
        error_text = None
        current_text_parts: list[str] = []

        def event(kind: Literal["text", "tool_call", "tool_result", "error", "done"], **values) -> AgentEvent:
            return AgentEvent(kind=kind, session_id=self.session_id, run_id=run_id, **values)

        def save_partial() -> None:
            content = "".join(current_text_parts)
            if content:
                self.state.append_message(
                    self.session_id,
                    {"role": "assistant", "content": content, "is_partial": True},
                )
                current_text_parts.clear()

        try:
            self.state.append_message(self.session_id, {"role": "user", "content": user_text})
            for _round in range(MAX_TOOL_ROUNDS):
                messages = [
                    {"role": "system", "content": self.system_prompt},
                    *self.state.messages(self.session_id),
                ]
                specs = [tool.openai_spec() for tool in self.tools.specs()]
                current_text_parts = []
                tool_calls: list[dict] = []
                finish_reason = None
                stream = self.provider.stream(messages, specs)
                try:
                    for item in stream:
                        if item.kind == "text" and item.text:
                            current_text_parts.append(item.text)
                            yield event("text", text=item.text)
                        elif item.kind == "tool_call" and item.tool_call is not None:
                            tool_calls.append(item.tool_call)
                        elif item.kind == "finish":
                            finish_reason = item.finish_reason
                finally:
                    close_stream = getattr(stream, "close", None)
                    if callable(close_stream):
                        close_stream()

                assistant_content = "".join(current_text_parts)
                if finish_reason is None:
                    raise IncompleteStreamError("provider stream ended without finish_reason")
                if finish_reason == "length":
                    save_partial()
                    status = "limit"
                    error_text = "provider reached the output length limit"
                    yield event("error", text=error_text)
                    break
                if finish_reason == "content_filter":
                    save_partial()
                    status = "error"
                    error_text = "provider filtered the response"
                    yield event("error", text=error_text)
                    break
                if finish_reason == "stop":
                    if tool_calls:
                        raise IncompleteStreamError("tool calls were returned without a tool_calls finish_reason")
                    if assistant_content:
                        self.state.append_message(
                            self.session_id,
                            {"role": "assistant", "content": assistant_content},
                        )
                    current_text_parts.clear()
                    status = "completed"
                    break
                if finish_reason != "tool_calls" or not tool_calls:
                    raise IncompleteStreamError(f"invalid tool round finish_reason: {finish_reason!r}")

                # Durable-before-side-effect: a restart can reconstruct the pending tool round.
                self.state.append_message(
                    self.session_id,
                    {
                        "role": "assistant",
                        "content": assistant_content or None,
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                                },
                            }
                            for call in tool_calls
                        ],
                    },
                )
                current_text_parts.clear()
                for call in tool_calls:
                    name = str(call.get("name", ""))
                    call_id = str(call.get("id", ""))
                    arguments = call.get("arguments")
                    yield event("tool_call", tool_call_id=call_id, tool_name=name, tool_args=arguments)
                    try:
                        output = self.tools.call(name, arguments)
                    except ToolError as exc:
                        output = f"[tool error] {exc}"
                    except Exception as exc:
                        output = f"[tool error] {type(exc).__name__}: {exc}"
                    self.state.append_message(
                        self.session_id,
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": output,
                        },
                    )
                    yield event("tool_result", tool_call_id=call_id, tool_name=name, text=output)
            else:
                status = "limit"
                error_text = f"stopped after {MAX_TOOL_ROUNDS} tool rounds"
                yield event("error", text=error_text)

            yield event("done", status=status)
        except GeneratorExit:
            save_partial()
            if status == "running":
                status = "cancelled"
            raise
        except Exception as exc:
            save_partial()
            status = "error"
            error_text = f"{type(exc).__name__}: {exc}"
            yield event("error", text=f"provider or run error: {error_text}")
            yield event("done", status=status)
        finally:
            if status == "running":
                status = "error"
                error_text = "run ended without a terminal outcome"
            self.state.finish_run(run_id, status, error_text)
