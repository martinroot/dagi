"""Small, workspace-scoped tool registry; shell is optional and approval-gated."""

from __future__ import annotations

import difflib
import json
import re
from decimal import Decimal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .state import StateStore

MAX_OUTPUT_CHARS = 8_000
MAX_FILE_BYTES = 250_000
MAX_FILE_DIFF_SOURCE_BYTES = 4_096
MAX_FILE_DIFF_BYTES = 8_000
MAX_PRESENTATION_BYTES = 16_000
MAX_INSPECT_RUNTIME_TOOLS = 32
MAX_INSPECT_RUNTIME_CHECKS = 12
SHELL_TIMEOUT_SECONDS = 30


class ToolError(Exception):
    """A user- or model-correctable tool error."""


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False
    presentation: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not isinstance(self.is_error, bool):
            raise TypeError("tool results require text content and a boolean error flag")
        if self.presentation is None:
            return
        if not isinstance(self.presentation, dict):
            raise TypeError("tool presentation metadata must be a JSON object")
        if set(self.presentation) - {"type", "summary", "artifacts", "diagnostics"}:
            raise ValueError("tool presentation metadata contains unsupported fields")
        view_type = self.presentation.get("type")
        summary = self.presentation.get("summary", "")
        artifacts = self.presentation.get("artifacts", [])
        diagnostics = self.presentation.get("diagnostics", {})
        if not isinstance(view_type, str) or not view_type.strip() or len(view_type) > 80:
            raise ValueError("tool presentation type must be non-empty text of at most 80 characters")
        if not isinstance(summary, str) or len(summary) > 1_000:
            raise ValueError("tool presentation summary must be text of at most 1000 characters")
        if not isinstance(artifacts, list) or len(artifacts) > 20 or any(not isinstance(item, dict) for item in artifacts):
            raise ValueError("tool presentation artifacts must be a list of at most 20 objects")
        if not isinstance(diagnostics, dict):
            raise ValueError("tool presentation diagnostics must be a JSON object")
        try:
            encoded = json.dumps(self.presentation, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("tool presentation metadata must contain only JSON values") from exc
        if len(encoded) > MAX_PRESENTATION_BYTES:
            raise ValueError(f"tool presentation metadata exceeds {MAX_PRESENTATION_BYTES} bytes")


@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: int
    run_id: str
    depth: int
    model: str
    cancel_event: Event | None = None
    register_provider: Callable[[Any], None] | None = None
    entry_point: str = "unknown"
    provider_call_limit: int | None = None
    budget_limit_usd: str | None = None


def _resolve(workspace: Path, raw_path: str) -> Path:
    candidate = (workspace / raw_path).resolve()
    if candidate != workspace and not candidate.is_relative_to(workspace):
        raise ToolError(f"path resolves outside workspace: {raw_path!r}")
    return candidate


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n...[truncated {len(text) - MAX_OUTPUT_CHARS} chars]"


def _validate_builtin_arguments(parameters: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Validate built-in tool arguments against the supported JSON Schema subset."""
    required = parameters.get("required", [])
    properties = parameters.get("properties", {})
    for name in required:
        if name not in arguments:
            raise ToolError(f"missing required argument '{name}'")

    def validate_value(name: str, value: Any, schema: dict[str, Any]) -> None:
        expected = schema.get("type")
        if expected is None:
            return
        matches = {
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "null": lambda item: item is None,
        }
        predicate = matches.get(expected)
        if predicate is not None and not predicate(value):
            raise ToolError(f"argument '{name}' must be {expected}")
        if expected == "array" and isinstance(value, list):
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    validate_value(f"{name}[{index}]", item, item_schema)

    if isinstance(properties, dict):
        for name, value in arguments.items():
            schema = properties.get(name)
            if isinstance(schema, dict):
                validate_value(name, value, schema)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., str | ToolResult]
    retryable: bool = False
    verify_effect: Callable[[dict[str, Any]], bool | None] | None = None
    context_aware: bool = False

    def openai_spec(self) -> dict[str, Any]:
        retry_state = "declared retryable" if self.retryable else "not declared retryable"
        verifier_state = (
            "An effect verifier is configured; the runtime uses its result and persisted outcome."
            if self.verify_effect is not None
            else "No effect verifier is configured; the runtime preserves uncertainty rather than inferring success."
        )
        recovery = (
            f" Runtime recovery is runtime-controlled; this tool is {retry_state}. "
            f"{verifier_state} Never infer permission to repeat an uncertain effect."
        )
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description.rstrip() + recovery,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(
        self,
        workspace: Path,
        state: StateStore,
        session_id: int,
        *,
        shell_enabled: bool = False,
        approve_shell: Callable[[str], bool] | None = None,
        memory_session_scope: bool = False,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state = state
        self.session_id = session_id
        self.approve_shell = approve_shell
        self.memory_session_scope = memory_session_scope
        self._tools: dict[str, Tool] = {}
        self._execution_context: ToolExecutionContext | None = None
        self._register_builtins(shell_enabled)
        self._builtin_tool_names = frozenset(self._tools)

    def register(self, tool: Tool) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tool.name):
            raise ValueError(f"invalid tool name: {tool.name!r}")
        if tool.name in self._tools:
            raise ValueError(f"tool name already registered: {tool.name}")
        self._tools[tool.name] = tool

    def set_execution_context(self, context: ToolExecutionContext) -> None:
        if context.session_id != self.session_id:
            raise ValueError("tool execution context must use the registry session")
        self._execution_context = context

    def specs(self) -> list[Tool]:
        return list(self._tools.values())

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool: {name!r}")
        if not isinstance(arguments, dict):
            raise ToolError("tool arguments must be a JSON object")
        if name in self._builtin_tool_names:
            _validate_builtin_arguments(tool.parameters, arguments)
        if tool.context_aware:
            if self._execution_context is None:
                raise ToolError(f"tool {name!r} requires an agent execution context")
            result = tool.handler(arguments, self._execution_context)
        else:
            result = tool.handler(arguments)
        if isinstance(result, ToolResult):
            return result
        if not isinstance(result, str):
            raise ToolError(f"tool {name!r} returned neither text nor ToolResult")
        return ToolResult(result)

    def recovery_metadata(self, name: str) -> dict[str, bool]:
        tool = self._tools.get(name)
        if tool is None:
            return {"retryable": False, "has_verifier": False}
        return {"retryable": tool.retryable, "has_verifier": tool.verify_effect is not None}

    def recovery_decision(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        persisted_retryable: bool | None = None,
    ) -> tuple[str, ToolResult | None]:
        tool = self._tools.get(name)
        if tool is None:
            return "uncertain", None
        retryable = tool.retryable and persisted_retryable is not False
        if tool.verify_effect is not None:
            try:
                verified = tool.verify_effect(arguments)
            except Exception:
                return "uncertain", None
            if verified is True:
                return "succeeded", ToolResult("The tool effect was verified after interruption.")
            if verified is False and retryable:
                return "pending", None
            return "uncertain", None
        if retryable:
            return "pending", None
        return "uncertain", None

    def _register_builtins(self, shell_enabled: bool) -> None:
        self.register(Tool(
            "read_file", "Read a UTF-8 text file within the workspace.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            self._read_file, retryable=True,
        ))
        self.register(Tool(
            "write_file", "Write a UTF-8 text file within the workspace.",
            {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            self._write_file, retryable=True, verify_effect=self._verify_write_effect,
        ))
        self.register(Tool(
            "list_dir", "List a directory within the workspace.",
            {"type": "object", "properties": {"path": {"type": "string"}}},
            self._list_dir, retryable=True,
        ))
        self.register(Tool(
            "inspect_runtime", "Inspect allowlisted facts about the current session, run, checks, tools, and limits.",
            {"type": "object", "properties": {}},
            self._inspect_runtime, retryable=True, context_aware=True,
        ))
        self.register(Tool(
            "search_memory", "Search messages saved from earlier sessions.",
            {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
            self._search_memory, retryable=True,
        ))
        self.register(Tool(
            "list_skills", "List saved reusable procedures.",
            {"type": "object", "properties": {}}, self._list_skills, retryable=True,
        ))
        self.register(Tool(
            "use_skill", "Load a saved procedure by name and record its use.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            self._use_skill,
        ))
        self.register(Tool(
            "create_skill", "Save a reusable procedure for future sessions.",
            {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "triggers": {"type": "array", "items": {"type": "string"}}, "body": {"type": "string"}}, "required": ["name", "description", "body"]},
            self._create_skill,
        ))
        if shell_enabled:
            self.register(Tool(
                "run_bash", "Run a shell command in the workspace after user approval.",
                {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
                self._run_bash,
            ))

    def _read_file(self, args: dict[str, Any]) -> ToolResult:
        path = _resolve(self.workspace, str(args["path"]))
        if not path.is_file():
            raise ToolError(f"not a file: {args['path']!r}")
        size_bytes = path.stat().st_size
        if size_bytes > MAX_FILE_BYTES:
            raise ToolError(f"file exceeds {MAX_FILE_BYTES} bytes")
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(self.workspace).as_posix()
        return ToolResult(
            _truncate(content),
            presentation={
                "type": "file",
                "summary": f"Read {relative}",
                "artifacts": [{"path": relative, "operation": "read"}],
                "diagnostics": {
                    "size_bytes": size_bytes,
                    "line_count": len(content.splitlines()),
                    "truncated": len(content) > MAX_OUTPUT_CHARS,
                },
            },
        )

    def _verify_write_effect(self, args: dict[str, Any]) -> bool | None:
        try:
            path = _resolve(self.workspace, str(args["path"]))
            if not path.exists():
                return False
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                return None
            return True if path.read_text(encoding="utf-8") == args.get("content") else None
        except Exception:
            return None

    def _bounded_file_diff(self, path: Path, relative: str, content: str) -> tuple[str | None, str | None, bool]:
        if len(relative.encode("utf-8")) > 512:
            return None, "path exceeds 512 bytes for diff metadata", False
        if not path.exists():
            return None, "new file", False
        if not path.is_file():
            return None, "previous path is not a regular file", False
        try:
            if path.stat().st_size > MAX_FILE_DIFF_SOURCE_BYTES:
                return None, f"previous file exceeds {MAX_FILE_DIFF_SOURCE_BYTES} bytes", False
            with path.open("rb") as stream:
                previous = stream.read(MAX_FILE_DIFF_SOURCE_BYTES + 1)
        except OSError:
            return None, "previous file could not be read", False
        if len(previous) > MAX_FILE_DIFF_SOURCE_BYTES:
            return None, f"previous file exceeds {MAX_FILE_DIFF_SOURCE_BYTES} bytes", False
        current = content.encode("utf-8")
        if len(current) > MAX_FILE_DIFF_SOURCE_BYTES:
            return None, f"new file exceeds {MAX_FILE_DIFF_SOURCE_BYTES} bytes", False
        try:
            previous_text = previous.decode("utf-8")
        except UnicodeDecodeError:
            return None, "previous file is not UTF-8 text", False
        diff = "".join(difflib.unified_diff(
            previous_text.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        ))
        encoded = diff.encode("utf-8")
        if len(encoded) <= MAX_FILE_DIFF_BYTES:
            return diff, None, False
        marker = "\n[diff preview truncated]"
        budget = MAX_FILE_DIFF_BYTES - len(marker.encode("utf-8"))
        bounded = encoded[:budget].decode("utf-8", errors="ignore") + marker
        return bounded, None, True

    def _write_file(self, args: dict[str, Any]) -> ToolResult:
        path = _resolve(self.workspace, str(args["path"]))
        content = args["content"]
        if not isinstance(content, str):
            raise ToolError("file content must be text")
        size_bytes = len(content.encode("utf-8"))
        if size_bytes > MAX_FILE_BYTES:
            raise ToolError(f"file content exceeds {MAX_FILE_BYTES} bytes")
        existed = path.exists()
        relative = path.relative_to(self.workspace).as_posix()
        diff, diff_reason, diff_truncated = self._bounded_file_diff(path, relative, content)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        operation = "update" if existed else "create"
        artifact = {"path": relative, "operation": operation}
        if diff is not None:
            artifact["diff"] = diff
        diagnostics = {
            "size_bytes": size_bytes,
            "created": not existed,
            "diff_available": diff is not None,
            "diff_truncated": diff_truncated,
        }
        if diff_reason:
            diagnostics["diff_reason"] = diff_reason
        return ToolResult(
            f"saved {relative} ({len(content)} chars)",
            presentation={
                "type": "file",
                "summary": f"{'Updated' if existed else 'Created'} {relative}",
                "artifacts": [artifact],
                "diagnostics": diagnostics,
            },
        )

    def _list_dir(self, args: dict[str, Any]) -> ToolResult:
        raw = str(args.get("path", "."))
        path = _resolve(self.workspace, raw)
        if not path.is_dir():
            raise ToolError(f"not a directory: {raw!r}")
        items = sorted(path.iterdir(), key=lambda item: item.name)
        content = "\n".join(item.name + ("/" if item.is_dir() else "") for item in items) or "(empty)"
        relative = path.relative_to(self.workspace).as_posix() or "."
        artifacts = []
        for item in items:
            kind = "symlink" if item.is_symlink() else "directory" if item.is_dir() else "file"
            child_path = item.relative_to(self.workspace).as_posix()
            artifacts.append({"name": item.name, "path": child_path, "kind": kind})
        return ToolResult(
            content,
            presentation={
                "type": "directory",
                "summary": f"Listed {relative}",
                "artifacts": artifacts,
                "diagnostics": {"entry_count": len(items), "empty": not items},
            },
        )

    def _inspect_runtime(self, _args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        session = self.state.get_session(context.session_id)
        run = self.state.get_run(context.run_id)
        if session is None or run is None or run["session_id"] != context.session_id:
            raise ToolError("runtime context no longer matches an active session and run")

        enabled_tools = sorted(self._tools)[:MAX_INSPECT_RUNTIME_TOOLS]
        usage = self.state.usage_summary_for_budget(context.run_id)
        calls_used = int(usage.get("provider_calls", 0))
        call_limit = context.provider_call_limit
        remaining_calls = max(0, call_limit - calls_used) if call_limit is not None else None
        budget = Decimal(context.budget_limit_usd) if context.budget_limit_usd is not None else None
        cost = usage.get("cost_usd")
        if budget is None:
            remaining_cost = None
            cost_status = "not_configured"
        elif cost is None:
            remaining_cost = None
            cost_status = "unknown"
        else:
            remaining_cost = str(max(Decimal("0"), budget - Decimal(cost)))
            cost_status = "known"

        current_goal = None
        for goal in self.state.list_goals(context.session_id):
            if context.run_id not in goal["runs"]:
                continue
            checks = []
            for check in goal["checks"][:MAX_INSPECT_RUNTIME_CHECKS]:
                summary: dict[str, Any] = {"type": str(check.get("type", "unknown"))}
                path = check.get("path")
                if isinstance(path, str):
                    summary["path"] = path[:256]
                    if len(path) > 256:
                        summary["path_truncated"] = True
                if summary["type"] == "file_contains" and isinstance(check.get("text"), str):
                    summary["required_text_length"] = len(check["text"])
                if summary["type"] == "command":
                    argv = check.get("argv")
                    summary["argument_count"] = len(argv) if isinstance(argv, list) else None
                    summary["arguments_omitted"] = True
                checks.append(summary)
            current_goal = {
                "goal_id": goal["goal_id"],
                "status": goal["status"],
                "iteration": goal["iteration"],
                "max_iterations": goal["max_iterations"],
                "checks": checks,
                "omitted_check_count": max(0, len(goal["checks"]) - len(checks)),
            }
            break

        snapshot = {
            "identity": {
                "agent_id": run["agent_id"],
                "agent_name": str(run["agent_name"])[:120],
                "session_id": context.session_id,
                "run_id": context.run_id,
                "parent_session_id": session.get("parent_id"),
                "parent_run_id": run.get("parent_run_id"),
                "role": "child" if session.get("parent_id") is not None else "root",
            },
            "environment": {
                "entry_point": context.entry_point if context.entry_point in {"cli", "web", "unknown"} else "unknown",
                "workspace": str(session.get("workspace") or ".")[:512],
                "resolved_workspace": str(self.workspace)[:512],
                "shell_enabled": "run_bash" in self._tools,
                "enabled_tools": enabled_tools,
                "omitted_tool_count": max(0, len(self._tools) - len(enabled_tools)),
            },
            "execution": {
                "status": run["status"],
                "depth": run["depth"],
                "parent_run_id": run.get("parent_run_id"),
            },
            "limits": {
                "provider_calls_used": calls_used,
                "provider_call_limit": call_limit,
                "remaining_provider_calls": remaining_calls,
                "budget_limit_usd": context.budget_limit_usd,
                "remaining_cost_usd": remaining_cost,
                "cost_status": cost_status,
            },
            "current_goal": current_goal,
        }
        serialized = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(serialized.encode("utf-8")) > MAX_OUTPUT_CHARS:
            raise ToolError("runtime inspection exceeds the output size limit")
        return ToolResult(serialized)

    def _search_memory(self, args: dict[str, Any]) -> ToolResult:
        hits = self.state.search_memory(
            str(args["query"]),
            int(args.get("limit", 10)),
            session_id=self.session_id if self.memory_session_scope else None,
        )
        content = "\n".join(
            f"[session {hit['session_id']}, {hit['role']}] {hit['snippet']}" for hit in hits
        ) or "(no matches)"
        displayed = hits[:20]
        return ToolResult(
            content,
            presentation={
                "type": "memory",
                "summary": f"Found {len(hits)} memory matches",
                "artifacts": [{
                    "message_id": hit["id"],
                    "session_id": hit["session_id"],
                    "role": hit["role"],
                    "snippet": hit["snippet"],
                    "created_at": hit["created_at"],
                } for hit in displayed],
                "diagnostics": {
                    "match_count": len(hits),
                    "displayed_count": len(displayed),
                    "omitted_count": max(0, len(hits) - len(displayed)),
                },
            },
        )

    def _list_skills(self, _args: dict[str, Any]) -> ToolResult:
        skills = self.state.list_skills()
        content = "\n".join(
            f"- {skill['name']}: {skill['description']}" for skill in skills
        ) or "(no skills yet)"
        count = len(skills)
        displayed = skills[:20]
        return ToolResult(
            content,
            presentation={
                "type": "skills",
                "summary": f"Listed {count} {'skill' if count == 1 else 'skills'}",
                "artifacts": [{
                    "name": str(skill["name"])[:80],
                    "description": str(skill["description"])[:160],
                    "triggers": [str(trigger)[:60] for trigger in skill.get("triggers", [])[:3]],
                    "use_count": skill.get("use_count", 0),
                } for skill in displayed],
                "diagnostics": {
                    "skill_count": count,
                    "displayed_count": len(displayed),
                    "omitted_count": max(0, count - len(displayed)),
                },
            },
        )

    def _use_skill(self, args: dict[str, Any]) -> ToolResult:
        name = str(args["name"])
        skill = self.state.get_skill(name)
        if skill is None:
            raise ToolError(f"no such skill: {name!r}")
        self.state.record_skill_use(name)
        updated = self.state.get_skill(name) or skill
        return ToolResult(
            f"# {skill['name']}\n{skill['description']}\n\n{skill['body']}",
            presentation={
                "type": "skill",
                "summary": f"Loaded skill {skill['name']}",
                "artifacts": [{
                    "name": str(skill["name"])[:80],
                    "description": str(skill["description"])[:160],
                    "triggers": [str(trigger)[:60] for trigger in skill.get("triggers", [])[:3]],
                    "use_count": updated.get("use_count", 0),
                }],
                "diagnostics": {"body_bytes": len(skill["body"].encode("utf-8"))},
            },
        )

    def _create_skill(self, args: dict[str, Any]) -> ToolResult:
        try:
            skill = self.state.create_skill(
                str(args["name"]), str(args["description"]),
                list(args.get("triggers") or []), str(args["body"]),
            )
        except Exception as exc:
            raise ToolError(f"could not save skill: {exc}") from exc
        return ToolResult(
            f"saved skill {skill['name']!r}",
            presentation={
                "type": "skill_created",
                "summary": f"Created skill {skill['name']}",
                "artifacts": [{
                    "name": str(skill["name"])[:80],
                    "description": str(skill["description"])[:160],
                    "triggers": [str(trigger)[:60] for trigger in skill.get("triggers", [])[:3]],
                    "use_count": skill.get("use_count", 0),
                }],
                "diagnostics": {"body_bytes": len(skill["body"].encode("utf-8"))},
            },
        )

    def _run_bash(self, args: dict[str, Any]) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolError("command must be non-empty text")
        if self.approve_shell is None or not self.approve_shell(command):
            raise ToolError("shell command declined")
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command, shell=True, cwd=self.workspace, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=SHELL_TIMEOUT_SECONDS, check=False,
            )
            exit_code = completed.returncode
            timed_out = False
            output = f"exit_code={exit_code}\n{completed.stdout or ''}"
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            timed_out = True
            output = f"[timeout after {SHELL_TIMEOUT_SECONDS}s]\n{exc.stdout or ''}"
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        return ToolResult(
            _truncate(output),
            presentation={
                "type": "command",
                "summary": f"Timed out after {SHELL_TIMEOUT_SECONDS}s" if timed_out else f"Exited with code {exit_code}",
                "artifacts": [{"exit_code": exit_code, "timed_out": timed_out}],
                "diagnostics": {
                    "duration_ms": duration_ms,
                    "output_truncated": len(output) > MAX_OUTPUT_CHARS,
                    "command_truncated": len(command) > 1_000,
                    "operator_approved": True,
                    "execution_boundary": "service-user host permissions; not an OS sandbox",
                },
            },
        )

    @staticmethod
    def arguments_for_call(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ToolError("tool arguments are not valid JSON") from exc
        if not isinstance(value, dict):
            raise ToolError("tool arguments must be a JSON object")
        return value
