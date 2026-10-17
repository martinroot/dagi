"""Small, workspace-scoped tool registry; shell is optional and approval-gated."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .state import StateStore

MAX_OUTPUT_CHARS = 8_000
MAX_FILE_BYTES = 250_000
SHELL_TIMEOUT_SECONDS = 30


class ToolError(Exception):
    """A user- or model-correctable tool error."""


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: int
    run_id: str
    depth: int
    model: str
    cancel_event: Event | None = None
    register_provider: Callable[[Any], None] | None = None


def _resolve(workspace: Path, raw_path: str) -> Path:
    candidate = (workspace / raw_path).resolve()
    if candidate != workspace and not candidate.is_relative_to(workspace):
        raise ToolError(f"path resolves outside workspace: {raw_path!r}")
    return candidate


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n...[truncated {len(text) - MAX_OUTPUT_CHARS} chars]"


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
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
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

    def _read_file(self, args: dict[str, Any]) -> str:
        path = _resolve(self.workspace, str(args["path"]))
        if not path.is_file():
            raise ToolError(f"not a file: {args['path']!r}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ToolError(f"file exceeds {MAX_FILE_BYTES} bytes")
        return _truncate(path.read_text(encoding="utf-8"))

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

    def _write_file(self, args: dict[str, Any]) -> str:
        path = _resolve(self.workspace, str(args["path"]))
        content = args["content"]
        if not isinstance(content, str):
            raise ToolError("file content must be text")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ToolError(f"file content exceeds {MAX_FILE_BYTES} bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"saved {path.relative_to(self.workspace)} ({len(content)} chars)"

    def _list_dir(self, args: dict[str, Any]) -> str:
        raw = str(args.get("path", "."))
        path = _resolve(self.workspace, raw)
        if not path.is_dir():
            raise ToolError(f"not a directory: {raw!r}")
        return "\n".join(sorted(item.name + ("/" if item.is_dir() else "") for item in path.iterdir())) or "(empty)"

    def _search_memory(self, args: dict[str, Any]) -> str:
        hits = self.state.search_memory(
            str(args["query"]),
            int(args.get("limit", 10)),
            session_id=self.session_id if self.memory_session_scope else None,
        )
        return "\n".join(
            f"[session {hit['session_id']}, {hit['role']}] {hit['snippet']}" for hit in hits
        ) or "(no matches)"

    def _list_skills(self, _args: dict[str, Any]) -> str:
        skills = self.state.list_skills()
        return "\n".join(
            f"- {skill['name']}: {skill['description']}" for skill in skills
        ) or "(no skills yet)"

    def _use_skill(self, args: dict[str, Any]) -> str:
        name = str(args["name"])
        skill = self.state.get_skill(name)
        if skill is None:
            raise ToolError(f"no such skill: {name!r}")
        self.state.record_skill_use(name)
        return f"# {skill['name']}\n{skill['description']}\n\n{skill['body']}"

    def _create_skill(self, args: dict[str, Any]) -> str:
        try:
            skill = self.state.create_skill(
                str(args["name"]), str(args["description"]),
                list(args.get("triggers") or []), str(args["body"]),
            )
        except Exception as exc:
            raise ToolError(f"could not save skill: {exc}") from exc
        return f"saved skill {skill['name']!r}"

    def _run_bash(self, args: dict[str, Any]) -> str:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolError("command must be non-empty text")
        if self.approve_shell is None or not self.approve_shell(command):
            raise ToolError("shell command declined")
        try:
            completed = subprocess.run(
                command, shell=True, cwd=self.workspace, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=SHELL_TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return _truncate(f"[timeout after {SHELL_TIMEOUT_SECONDS}s]\n{exc.stdout or ''}")
        return _truncate(f"exit_code={completed.returncode}\n{completed.stdout or ''}")

    @staticmethod
    def arguments_for_call(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ToolError("tool arguments are not valid JSON") from exc
        if not isinstance(value, dict):
            raise ToolError("tool arguments must be a JSON object")
        return value
