"""Bounded synchronous parent-to-child agent delegation."""

from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from .agent import Agent
from .context import ContextBuilder
from .provider import OpenAICompatibleProvider
from .state import StateStore
from .tools import Tool, ToolExecutionContext, ToolRegistry, ToolResult
from .usage import UsagePolicy

ProviderFactory = Callable[[str, str, str], OpenAICompatibleProvider]


class DelegationManager:
    def __init__(
        self,
        state: StateStore,
        workspace,
        *,
        api_key: str,
        base_url: str,
        provider_factory: ProviderFactory = OpenAICompatibleProvider,
        usage_policy: UsagePolicy | None = None,
        compression_model: str | None = None,
        context_limit_tokens: int = 32_768,
        context_max_tool_result_chars: int = 4_000,
        max_depth: int = 2,
        max_children: int = 3,
        shell_enabled: bool = False,
        approve_shell: Callable[[str], bool] | None = None,
    ):
        if max_depth < 0 or max_children < 0:
            raise ValueError("delegation limits must not be negative")
        self.state = state
        self.workspace = workspace
        self.api_key = api_key
        self.base_url = base_url
        self.provider_factory = provider_factory
        self.usage_policy = usage_policy or UsagePolicy()
        self.compression_model = compression_model
        self.context_limit_tokens = context_limit_tokens
        self.context_max_tool_result_chars = context_max_tool_result_chars
        self.max_depth = max_depth
        self.max_children = max_children
        self.shell_enabled = shell_enabled
        self.approve_shell = approve_shell

    def register(self, tools: ToolRegistry) -> None:
        tools.register(Tool(
            name="delegate_task",
            description="Delegate an explicit task and optional context to a bounded child agent.",
            parameters={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The specific task for the child."},
                    "model": {"type": "string", "description": "Optional child model override."},
                    "context": {"type": "string", "description": "Only the context explicitly approved for transfer."},
                },
                "required": ["task"],
            },
            handler=self._delegate,
            retryable=False,
            context_aware=True,
        ))

    def _delegate(self, args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        task = args.get("task")
        transferred_context = args.get("context", "")
        model = args.get("model") or context.model
        if not isinstance(task, str) or not task.strip():
            return ToolResult("delegated task must be non-empty text", is_error=True)
        if not isinstance(transferred_context, str):
            return ToolResult("delegated context must be text", is_error=True)
        if len(task) > 8_000 or len(transferred_context) > 24_000:
            return ToolResult("delegated task or context exceeds the configured transfer limit", is_error=True)
        if context.depth >= self.max_depth:
            return ToolResult(f"delegation depth limit reached ({self.max_depth})", is_error=True)
        if self.state.count_child_runs_in_budget_group(context.run_id) >= self.max_children:
            return ToolResult(f"child-agent limit reached ({self.max_children})", is_error=True)
        if not isinstance(model, str) or not model.strip():
            return ToolResult("child model must be non-empty text", is_error=True)
        child_session: int | None = None
        child_run: str | None = None
        try:
            self.usage_policy.validate_model(model)
            parent = self.state.get_run(context.run_id)
            if parent is None:
                return ToolResult("parent run does not exist", is_error=True)
            child_session = self.state.create_session(f"Child: {task[:80]}")
            child_agent_id = str(uuid4())
            child_run = self.state.create_run(
                child_session,
                agent_id=child_agent_id,
                parent_run_id=context.run_id,
                agent_name=model,
            )
            provider = self.provider_factory(model, self.api_key, self.base_url)
            compression_model = self.compression_model or model
            compressor = self.provider_factory(compression_model, self.api_key, self.base_url)
            if context.register_provider is not None:
                context.register_provider(provider)
                context.register_provider(compressor)
            child_tools = ToolRegistry(
                self.workspace,
                self.state,
                child_session,
                shell_enabled=self.shell_enabled,
                approve_shell=self.approve_shell,
                memory_session_scope=True,
            )
            self.register(child_tools)
            context_builder = ContextBuilder(
                self.state,
                max_tokens=self.context_limit_tokens,
                max_tool_result_chars=self.context_max_tool_result_chars,
                compression_provider=compressor,
                usage_policy=self.usage_policy,
            )
            child_agent = Agent(
                provider,
                lambda _session_id: child_tools,
                self.state,
                usage_policy=self.usage_policy,
                context_builder=context_builder,
                agent_id=child_agent_id,
                agent_name=model,
            )
            prompt = (
                f"Delegated task:\n{task.strip()}\n\n"
                "Explicitly transferred context:\n"
                f"{transferred_context.strip() if transferred_context.strip() else '(none)'}\n\n"
                "Return a concise result and identify any uncertainty."
            )
            list(child_agent.run_turn(
                prompt,
                session_id=child_session,
                run_id=child_run,
                cancel_event=context.cancel_event,
                register_provider=context.register_provider,
            ))
            completed = self.state.get_run(child_run)
            if completed is None or completed["status"] != "completed":
                status = completed["status"] if completed else "missing"
                error = completed.get("error") if completed else "child run disappeared"
                return ToolResult(f"Child run {child_run} ended with {status}: {error or 'no final result'}", is_error=True)
            child_messages = self.state.messages(child_session)
            answer = next(
                (message["content"] for message in reversed(child_messages)
                 if message["role"] == "assistant" and message.get("content")),
                "",
            )
            if not answer:
                return ToolResult(f"Child run {child_run} completed without a text result", is_error=True)
            return ToolResult(f"Child run {child_run} result:\n{answer}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if child_run is not None and child_session is not None:
                run = self.state.get_run(child_run)
                if run is not None and run["status"] == "running":
                    full_error = f"child agent setup failed: {error}"
                    for kind, text, status in (("error", full_error, None), ("done", None, "error")):
                        self.state.append_run_event(child_session, child_run, {
                            "kind": kind,
                            "session_id": child_session,
                            "run_id": child_run,
                            "text": text,
                            "status": status,
                        })
                    self.state.finish_run(child_run, "error", full_error)
            return ToolResult(f"Child agent could not complete the task: {error}", is_error=True)
