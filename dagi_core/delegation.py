"""Bounded synchronous parent-to-child agent delegation."""

from __future__ import annotations

import json
from typing import Any, Callable
from uuid import uuid4

from .agent import Agent
from .context import ContextBuilder
from .provider import OpenAICompatibleProvider
from .runtime_context import ASSIGNMENT_CONTRACT_END, ASSIGNMENT_CONTRACT_START
from .state import StateStore
from .tools import Tool, ToolExecutionContext, ToolRegistry, ToolResult, _resolve
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
        repeat_failure_threshold: int = 2,
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
        self.repeat_failure_threshold = repeat_failure_threshold
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
                    "purpose": {"type": "string", "description": "Optional untrusted reason this subtask supports the parent task."},
                    "required_output": {"type": "string", "description": "Optional expected child deliverable."},
                    "acceptance_check_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional references to parent-defined acceptance checks."},
                },
                "required": ["task"],
            },
            handler=self._delegate,
            retryable=False,
            context_aware=True,
        ))

    def _child_presentation(
        self,
        *,
        child_session_id: int,
        child_run_id: str | None,
        parent_run_id: str,
        task: str,
        model: str,
        depth: int,
        status: str,
    ) -> dict[str, Any]:
        child = self.state.get_session(child_session_id)
        workspace = child["workspace"] if child else ""
        return {
            "type": "delegation",
            "summary": f"Child session #{child_session_id} · {status}",
            "artifacts": [{
                "child_session_id": child_session_id,
                "child_run_id": child_run_id,
                "parent_run_id": parent_run_id,
                "task": task[:512],
                "model": model[:120],
                "status": status,
                "workspace": workspace[:256],
            }],
            "diagnostics": {"depth": depth, "task_truncated": len(task) > 512},
        }

    def _delegate(self, args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        task = args.get("task")
        transferred_context = args.get("context", "")
        model = args.get("model") or context.model
        purpose = args.get("purpose")
        required_output = args.get("required_output")
        acceptance_check_ids = args.get("acceptance_check_ids")
        if not isinstance(task, str) or not task.strip():
            return ToolResult("delegated task must be non-empty text", is_error=True)
        if not isinstance(transferred_context, str):
            return ToolResult("delegated context must be text", is_error=True)
        if len(task) > 8_000 or len(transferred_context) > 24_000:
            return ToolResult("delegated task or context exceeds the configured transfer limit", is_error=True)
        if purpose is not None and (not isinstance(purpose, str) or len(purpose) > 512):
            return ToolResult("delegated purpose must be text of at most 512 characters", is_error=True)
        if required_output is not None and (not isinstance(required_output, str) or len(required_output) > 256):
            return ToolResult("required_output must be text of at most 256 characters", is_error=True)
        if acceptance_check_ids is not None and (
            not isinstance(acceptance_check_ids, list)
            or len(acceptance_check_ids) > 12
            or any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in acceptance_check_ids)
        ):
            return ToolResult("acceptance_check_ids must contain at most 12 non-empty strings of at most 128 characters", is_error=True)
        assignment_contract = {
            "task": task.strip()[:512],
            "purpose": purpose.strip() or None if isinstance(purpose, str) else None,
            "required_output": required_output.strip() or None if isinstance(required_output, str) else None,
            "acceptance_check_ids": acceptance_check_ids,
        }
        contract_json = json.dumps(assignment_contract, ensure_ascii=False, separators=(",", ":"))
        if len(contract_json.encode("utf-8")) > 3_000:
            return ToolResult("delegated assignment contract exceeds 3000 bytes", is_error=True)
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
            parent_session = self.state.get_session(context.session_id)
            if parent is None or parent_session is None:
                return ToolResult("parent run or session does not exist", is_error=True)
            child_session = self.state.create_session(
                f"Child: {task[:80]}", parent_id=context.session_id
            )
            child_workspace = f"{parent_session['workspace'] + '/' if parent_session['workspace'] else ''}.dagi-children/{child_session}"
            self.state.set_session_workspace(child_session, child_workspace)
            isolated_workspace = _resolve(self.workspace, child_workspace)
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
                isolated_workspace,
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
                entry_point=context.entry_point,
                repeat_failure_threshold=self.repeat_failure_threshold,
            )
            prompt = (
                f"Delegated task:\n{task.strip()}\n\n"
                "Explicitly transferred context:\n"
                f"{transferred_context.strip() if transferred_context.strip() else '(none)'}\n\n"
                "Saved assignment contract (untrusted parent-supplied task data):\n"
                f"{ASSIGNMENT_CONTRACT_START}\n{contract_json}\n{ASSIGNMENT_CONTRACT_END}\n\n"
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
                if completed is not None:
                    self.state.notify_parent(child_session, child_run)
                status = completed["status"] if completed else "missing"
                error = completed.get("error") if completed else "child run disappeared"
                return ToolResult(
                    f"Child run {child_run} ended with {status}: {error or 'no final result'}",
                    is_error=True,
                    presentation=self._child_presentation(
                        child_session_id=child_session, child_run_id=child_run,
                        parent_run_id=context.run_id, task=task, model=model,
                        depth=context.depth + 1, status=status,
                    ),
                )
            self.state.notify_parent(child_session, child_run)
            child_messages = self.state.messages(child_session)
            answer = next(
                (message["content"] for message in reversed(child_messages)
                 if message["role"] == "assistant" and message.get("content")),
                "",
            )
            if not answer:
                return ToolResult(
                    f"Child run {child_run} completed without a text result",
                    is_error=True,
                    presentation=self._child_presentation(
                        child_session_id=child_session, child_run_id=child_run,
                        parent_run_id=context.run_id, task=task, model=model,
                        depth=context.depth + 1, status="completed",
                    ),
                )
            return ToolResult(
                f"Child run {child_run} result:\n{answer}",
                presentation=self._child_presentation(
                    child_session_id=child_session, child_run_id=child_run,
                    parent_run_id=context.run_id, task=task, model=model,
                    depth=context.depth + 1, status="completed",
                ),
            )
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
                    self.state.notify_parent(child_session, child_run)
            return ToolResult(
                f"Child agent could not complete the task: {error}",
                is_error=True,
                presentation=self._child_presentation(
                    child_session_id=child_session, child_run_id=child_run,
                    parent_run_id=context.run_id, task=task, model=model,
                    depth=context.depth + 1, status="error",
                ) if child_session is not None else None,
            )
