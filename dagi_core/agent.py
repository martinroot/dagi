"""The minimal Hermes-style loop: model response, tool round, durable transcript."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterator, Literal

from .provider import OpenAICompatibleProvider, StreamEvent
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
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None


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
        self.state.append_message(self.session_id, {"role": "user", "content": user_text})

        for _round in range(MAX_TOOL_ROUNDS):
            messages = [
                {"role": "system", "content": self.system_prompt},
                *self.state.messages(self.session_id),
            ]
            specs = [tool.openai_spec() for tool in self.tools.specs()]
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            try:
                for event in self.provider.stream(messages, specs):
                    if event.kind == "text" and event.text:
                        text_parts.append(event.text)
                        yield AgentEvent(kind="text", text=event.text)
                    elif event.kind == "tool_call" and event.tool_call is not None:
                        tool_calls.append(event.tool_call)
            except Exception as exc:
                yield AgentEvent(kind="error", text=f"provider error: {exc}")
                yield AgentEvent(kind="done")
                return

            assistant_content = "".join(text_parts)
            if not tool_calls:
                if assistant_content:
                    self.state.append_message(
                        self.session_id, {"role": "assistant", "content": assistant_content}
                    )
                yield AgentEvent(kind="done")
                return

            # Durable-before-side-effect: a process restart can reconstruct the pending tool round.
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
            for call in tool_calls:
                name = str(call.get("name", ""))
                arguments = call.get("arguments")
                yield AgentEvent(kind="tool_call", tool_name=name, tool_args=arguments)
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
                        "tool_call_id": str(call.get("id", "")),
                        "name": name,
                        "content": output,
                    },
                )
                yield AgentEvent(kind="tool_result", tool_name=name, text=output)

        yield AgentEvent(kind="error", text=f"stopped after {MAX_TOOL_ROUNDS} tool rounds")
        yield AgentEvent(kind="done")
