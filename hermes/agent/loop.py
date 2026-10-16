"""The core agent turn: stream a response, execute any tool calls, repeat
until the model stops calling tools -- then, if the turn was complex enough,
hand the transcript to the learning loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal

from hermes.learning import curator
from hermes.memory.store import MemoryStore
from hermes.providers.base import LLMProvider, Message, ToolCall, ToolResult
from hermes.skills.manager import SkillManager

from .prompts import MAIN_SYSTEM_PROMPT
from .tools import ToolExecutionError, ToolRegistry

MAX_TOOL_ITERATIONS = 25
SKILL_SUGGESTION_THRESHOLD = 3  # tool calls in one turn before offering to save a skill


@dataclass
class TurnEvent:
    kind: Literal["text", "tool_call", "tool_result", "skill_created", "error", "done"]
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None


class AgentLoop:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        memory: MemoryStore,
        skills: SkillManager,
        session_id: int,
        system_prompt: str = MAIN_SYSTEM_PROMPT,
    ):
        self.provider = provider
        self.tools = tools
        self.memory = memory
        self.skills = skills
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.history: list[Message] = []
        self._turn_log: list[tuple[str, str]] = []

    @property
    def turn_log(self) -> list[tuple[str, str]]:
        return self._turn_log

    def run_turn(self, user_input: str) -> Iterator[TurnEvent]:
        self.history.append(Message(role="user", content=user_input))
        self.memory.add_message(self.session_id, "user", user_input)
        self._turn_log.append(("user", user_input))

        tool_call_count = 0
        hit_iteration_limit = True
        provider_failed = False

        for _ in range(MAX_TOOL_ITERATIONS):
            assistant_text_parts: list[str] = []
            tool_calls: list[ToolCall] = []

            try:
                for chunk in self.provider.stream(
                    self.system_prompt, self.history, self.tools.specs()
                ):
                    if chunk.kind == "text_delta" and chunk.text:
                        assistant_text_parts.append(chunk.text)
                        yield TurnEvent(kind="text", text=chunk.text)
                    elif chunk.kind == "tool_call" and chunk.tool_call:
                        tool_calls.append(chunk.tool_call)
            except Exception as exc:  # network/auth/rate-limit errors must not crash the loop
                yield TurnEvent(kind="error", text=f"provider error: {exc}")
                provider_failed = True
                break

            assistant_text = "".join(assistant_text_parts)
            self.history.append(
                Message(role="assistant", content=assistant_text, tool_calls=tool_calls)
            )
            if assistant_text:
                self.memory.add_message(self.session_id, "assistant", assistant_text)
                self._turn_log.append(("assistant", assistant_text))

            if not tool_calls:
                hit_iteration_limit = False
                break

            tool_results: list[ToolResult] = []
            for tc in tool_calls:
                tool_call_count += 1
                yield TurnEvent(kind="tool_call", tool_name=tc.name, tool_args=tc.arguments)
                try:
                    output = self.tools.call(tc.name, tc.arguments)
                    is_error = False
                except ToolExecutionError as exc:
                    output = str(exc)
                    is_error = True
                except Exception as exc:  # a broken tool must not crash the whole loop
                    output = f"[error] {exc}"
                    is_error = True
                yield TurnEvent(kind="tool_result", tool_name=tc.name, text=output)

                logged = f"{tc.name}({tc.arguments}) -> {output}"
                self.memory.add_message(self.session_id, "tool", logged)
                self._turn_log.append(("tool", logged))

                tool_results.append(
                    ToolResult(tool_call_id=tc.id, name=tc.name, content=output, is_error=is_error)
                )

            self.history.append(Message(role="tool", tool_results=tool_results))

        if provider_failed:
            hit_iteration_limit = False

        if hit_iteration_limit:
            yield TurnEvent(
                kind="text",
                text="\n[hermes] stopped after hitting the tool-call limit for this turn.\n",
            )

        if not provider_failed and tool_call_count >= SKILL_SUGGESTION_THRESHOLD:
            try:
                name = curator.propose_skill(
                    self.provider, self.skills, self._turn_log, self.session_id
                )
            except Exception:
                name = None
            if name:
                yield TurnEvent(kind="skill_created", tool_name=name)

        yield TurnEvent(kind="done")

    def close_session(self) -> None:
        if not self._turn_log:
            return
        try:
            summary = curator.summarize_session(self.provider, self._turn_log)
        except Exception:
            return
        self.memory.set_session_summary(self.session_id, summary)
