"""The minimal Hermes-style loop: model response, tool round, durable transcript."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Generator, Iterator, Literal

from .provider import IncompleteStreamError, OpenAICompatibleProvider
from .state import StateStore
from .tools import ToolError, ToolRegistry, ToolResult
from .usage import UsagePolicy

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
    is_error: bool | None = None


class Agent:
    def __init__(
        self,
        provider: OpenAICompatibleProvider,
        tools: ToolRegistry,
        state: StateStore,
        session_id: int,
        system_prompt: str = SYSTEM_PROMPT,
        usage_policy: UsagePolicy | None = None,
    ):
        self.provider = provider
        self.model = getattr(provider, "model", "unknown")
        self.tools = tools
        self.state = state
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.usage_policy = usage_policy or UsagePolicy()

    def run_turn(self, user_text: str) -> Iterator[AgentEvent]:
        if not user_text.strip():
            raise ValueError("user message must not be empty")
        self.usage_policy.validate_model(self.model)
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

        def dispatch_tool_call(call: dict) -> Generator[AgentEvent, None, str]:
            call_id = str(call.get("id", call.get("tool_call_id", "")))
            name = str(call["name"])
            arguments = call["arguments"]
            self.state.mark_tool_call_running(call_id)
            yield event("tool_call", tool_call_id=call_id, tool_name=name, tool_args=arguments)
            outcome = "succeeded"
            error = None
            try:
                returned = self.tools.call(name, arguments)
                result = returned if isinstance(returned, ToolResult) else ToolResult(str(returned))
                if result.is_error:
                    outcome = "failed"
                    error = result.content
            except ToolError as exc:
                result = ToolResult(f"[tool error] {exc}", is_error=True)
                outcome = "failed"
                error = str(exc)
            except Exception as exc:
                result = ToolResult(f"[tool outcome unknown] {type(exc).__name__}: {exc}", is_error=True)
                outcome = "uncertain"
                error = str(exc)
            self.state.append_message(
                self.session_id,
                {"role": "tool", "tool_call_id": call_id, "name": name, "content": result.content},
            )
            self.state.finish_tool_call(call_id, outcome, result.content, error)
            yield event(
                "tool_result", tool_call_id=call_id, tool_name=name,
                text=result.content, is_error=result.is_error,
            )
            return outcome

        try:
            running = self.state.list_tool_calls(self.session_id, ("running",))
            uncertain = self.state.list_tool_calls(self.session_id, ("uncertain",))
            for call in uncertain:
                decision, verified_result = self.tools.recovery_decision(
                    call["name"], call["arguments"], persisted_retryable=call["retryable"]
                )
                if decision == "pending":
                    self.state.reconcile_tool_call(call["tool_call_id"], "pending")
                elif decision == "succeeded" and verified_result is not None:
                    self.state.append_message(
                        self.session_id,
                        {
                            "role": "tool", "tool_call_id": call["tool_call_id"],
                            "name": call["name"], "content": verified_result.content,
                        },
                    )
                    self.state.reconcile_tool_call(
                        call["tool_call_id"], "succeeded", verified_result.content
                    )
                    yield event(
                        "tool_result", tool_call_id=call["tool_call_id"],
                        tool_name=call["name"], text=verified_result.content,
                        is_error=verified_result.is_error,
                    )
            unresolved = running + self.state.list_tool_calls(self.session_id, ("uncertain",))
            if unresolved:
                call_id = unresolved[0]["tool_call_id"]
                error_text = f"tool call {call_id} has an unknown outcome; inspect it before continuing"
                status = "error"
                yield event("error", text=error_text)
                yield event("done", status=status)
                return

            pending = self.state.list_tool_calls(self.session_id, ("pending",))
            for call in pending:
                outcome = yield from dispatch_tool_call(call)
                if outcome == "uncertain":
                    error_text = f"tool call {call['tool_call_id']} has an unknown outcome; stopping this run"
                    status = "error"
                    yield event("error", text=error_text)
                    yield event("done", status=status)
                    return

            self.state.append_message(self.session_id, {"role": "user", "content": user_text})
            for _round in range(MAX_TOOL_ROUNDS):
                stop_reason = self.usage_policy.stop_reason(self.state.usage_summary(run_id))
                if stop_reason:
                    status = "limit"
                    error_text = stop_reason
                    yield event("error", text=error_text)
                    break
                messages = [
                    {"role": "system", "content": self.system_prompt},
                    *self.state.messages(self.session_id),
                ]
                specs = [tool.openai_spec() for tool in self.tools.specs()]
                current_text_parts = []
                tool_calls: list[dict] = []
                finish_reason = None
                actual_usage = None
                response_seen = False
                provider_call_id = self.state.create_provider_call(run_id, self.model, "agent")
                stream = None
                try:
                    stream = self.provider.stream(messages, specs)
                    for item in stream:
                        if item.kind == "text" and item.text:
                            response_seen = True
                            current_text_parts.append(item.text)
                            yield event("text", text=item.text)
                        elif item.kind == "tool_call" and item.tool_call is not None:
                            response_seen = True
                            tool_calls.append(item.tool_call)
                        elif item.kind == "usage" and item.usage is not None:
                            actual_usage = item.usage
                        elif item.kind == "finish":
                            response_seen = True
                            finish_reason = item.finish_reason
                finally:
                    close_stream = getattr(stream, "close", None)
                    if callable(close_stream):
                        close_stream()
                    response_text = "".join(current_text_parts) + json.dumps(tool_calls, ensure_ascii=False)
                    usage = self.usage_policy.measure(
                        self.model, messages, response_text, actual_usage,
                        tools=specs,
                        estimate=self.usage_policy.estimate_missing and response_seen,
                    )
                    self.state.record_usage(provider_call_id, usage.as_dict())

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

                stop_reason = self.usage_policy.stop_reason(self.state.usage_summary(run_id))
                if stop_reason:
                    save_partial()
                    status = "limit"
                    error_text = stop_reason
                    yield event("error", text=error_text)
                    break

                calls_for_storage = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                        },
                    }
                    for call in tool_calls
                ]
                self.state.save_tool_round(
                    self.session_id,
                    run_id,
                    {"role": "assistant", "content": assistant_content or None, "tool_calls": calls_for_storage},
                    tool_calls,
                    recovery_metadata={
                        call["id"]: self.tools.recovery_metadata(call["name"])
                        for call in tool_calls
                    },
                )
                current_text_parts.clear()
                for call in tool_calls:
                    outcome = yield from dispatch_tool_call(call)
                    if outcome == "uncertain":
                        error_text = f"tool call {call['id']} has an unknown outcome; stopping this run"
                        status = "error"
                        yield event("error", text=error_text)
                        break
                if status == "error":
                    break
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
