"""Small, workspace-scoped tool registry; shell is optional and approval-gated."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .state import StateStore

MAX_OUTPUT_CHARS = 8_000
MAX_FILE_BYTES = 250_000
SHELL_TIMEOUT_SECONDS = 30


class ToolError(Exception):
    """A user- or model-correctable tool error."""


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
    handler: Callable[[dict[str, Any]], str]

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
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state = state
        self.session_id = session_id
        self.approve_shell = approve_shell
        self._tools: dict[str, Tool] = {}
        self._register_builtins(shell_enabled)

    def _register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def specs(self) -> list[Tool]:
        return list(self._tools.values())

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool: {name!r}")
        if not isinstance(arguments, dict):
            raise ToolError("tool arguments must be a JSON object")
        return tool.handler(arguments)

    def _register_builtins(self, shell_enabled: bool) -> None:
        self._register(Tool(
            "read_file", "Read a UTF-8 text file within the workspace.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            self._read_file,
        ))
        self._register(Tool(
            "write_file", "Write a UTF-8 text file within the workspace.",
            {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            self._write_file,
        ))
        self._register(Tool(
            "list_dir", "List a directory within the workspace.",
            {"type": "object", "properties": {"path": {"type": "string"}}},
            self._list_dir,
        ))
        self._register(Tool(
            "search_memory", "Search messages saved from earlier sessions.",
            {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
            self._search_memory,
        ))
        self._register(Tool(
            "list_skills", "List saved reusable procedures.",
            {"type": "object", "properties": {}}, self._list_skills,
        ))
        self._register(Tool(
            "use_skill", "Load a saved procedure by name and record its use.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            self._use_skill,
        ))
        self._register(Tool(
            "create_skill", "Save a reusable procedure for future sessions.",
            {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "triggers": {"type": "array", "items": {"type": "string"}}, "body": {"type": "string"}}, "required": ["name", "description", "body"]},
            self._create_skill,
        ))
        if shell_enabled:
            self._register(Tool(
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
        hits = self.state.search_memory(str(args["query"]), int(args.get("limit", 10)))
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
