"""Built-in tool registry: shell, filesystem, memory search, and the skill
CRUD operations that make up the learning loop.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hermes.memory.store import MemoryStore
from hermes.providers.base import ToolSpec
from hermes.skills.manager import SkillManager

MAX_OUTPUT_CHARS = 8000
BASH_TIMEOUT_SECONDS = 120


@dataclass
class Tool:
    spec: ToolSpec
    handler: Callable[[dict[str, Any]], str]


class ToolExecutionError(Exception):
    pass


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _resolve_in_workspace(workspace: Path, raw_path: str) -> Path:
    candidate = (workspace / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    if not (candidate == workspace or candidate.is_relative_to(workspace)):
        raise ToolExecutionError(
            f"Path {raw_path!r} resolves outside the workspace ({workspace}); refusing."
        )
    return candidate


class ToolRegistry:
    """Owns tool dependencies (workspace, memory, skills) and dispatches calls."""

    def __init__(
        self,
        workspace: Path,
        memory: MemoryStore,
        skills: SkillManager,
        session_id: int,
        enable_shell: bool = False,
        enable_write: bool = True,
        approve_shell: Callable[[str], bool] | None = None,
    ):
        self.workspace = workspace
        self.memory = memory
        self.skills = skills
        self.session_id = session_id
        self.enable_shell = enable_shell
        self.enable_write = enable_write
        self.approve_shell = approve_shell
        self._tools: dict[str, Tool] = {}
        self._register_builtins()

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolExecutionError(f"Unknown tool: {name!r}")
        return tool.handler(arguments)

    def _register(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], str]) -> None:
        self._tools[spec.name] = Tool(spec=spec, handler=handler)

    # -- handlers -----------------------------------------------------

    def _register_builtins(self) -> None:
        if self.enable_shell:
            self._register(
                ToolSpec(
                    name="run_bash",
                    description=(
                        "Execute a shell command in the workspace directory and return its "
                        "combined stdout/stderr and exit code."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                    },
                ),
                self._run_bash,
            )
        self._register(
            ToolSpec(
                name="read_file",
                description="Read a UTF-8 text file, relative to the workspace root.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            self._read_file,
        )
        if self.enable_write:
            self._register(
                ToolSpec(
                    name="write_file",
                    description=(
                        "Write (overwriting) a UTF-8 text file, relative to the workspace root. "
                        "Parent directories are created as needed."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                ),
                self._write_file,
            )
        self._register(
            ToolSpec(
                name="list_dir",
                description="List entries in a directory, relative to the workspace root.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": "."}},
                },
            ),
            self._list_dir,
        )
        self._register(
            ToolSpec(
                name="search_memory",
                description=(
                    "Full-text search across every message from every past session. "
                    "Use this to recall prior conversations before saying you don't know."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            ),
            self._search_memory,
        )
        self._register(
            ToolSpec(
                name="list_skills",
                description="List every skill in the skill library with description and use count.",
                input_schema={"type": "object", "properties": {}},
            ),
            self._list_skills,
        )
        self._register(
            ToolSpec(
                name="use_skill",
                description="Load a skill's full procedure by name so you can follow it.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            self._use_skill,
        )
        self._register(
            ToolSpec(
                name="create_skill",
                description=(
                    "Save a new reusable skill to the library: a concrete, step-by-step "
                    "markdown procedure you can follow again next time."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "triggers": {"type": "array", "items": {"type": "string"}},
                        "body": {"type": "string"},
                    },
                    "required": ["name", "description", "body"],
                },
            ),
            self._create_skill,
        )

    def _run_bash(self, args: dict[str, Any]) -> str:
        command = args["command"]
        if self.approve_shell is None or not self.approve_shell(command):
            raise ToolExecutionError("shell command declined or no approval callback was configured")
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=BASH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return f"[error] command timed out after {BASH_TIMEOUT_SECONDS}s"
        output = result.stdout + result.stderr
        return _truncate(f"exit_code={result.returncode}\n{output}")

    def _read_file(self, args: dict[str, Any]) -> str:
        path = _resolve_in_workspace(self.workspace, args["path"])
        if not path.exists():
            return f"[error] no such file: {path}"
        return _truncate(path.read_text(encoding="utf-8", errors="replace"))

    def _write_file(self, args: dict[str, Any]) -> str:
        path = _resolve_in_workspace(self.workspace, args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return f"wrote {len(args['content'])} chars to {path}"

    def _list_dir(self, args: dict[str, Any]) -> str:
        path = _resolve_in_workspace(self.workspace, args.get("path", "."))
        if not path.exists():
            return f"[error] no such directory: {path}"
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return "\n".join(entries) or "(empty)"

    def _search_memory(self, args: dict[str, Any]) -> str:
        hits = self.memory.search(args["query"], limit=args.get("limit", 10))
        if not hits:
            return "(no matches)"
        lines = [
            f"[session {h.session_id}, {h.role}, {h.created_at}] {h.snippet}" for h in hits
        ]
        return "\n".join(lines)

    def _list_skills(self, args: dict[str, Any]) -> str:
        skills = self.skills.list_skills()
        if not skills:
            return "(no skills yet)"
        return "\n".join(
            f"- {s.name} (used {s.use_count}x): {s.description}" for s in skills
        )

    def _use_skill(self, args: dict[str, Any]) -> str:
        skill = self.skills.get_skill(args["name"])
        if skill is None:
            return f"[error] no such skill: {args['name']!r}"
        self.skills.record_use(skill.name)
        return f"# Skill: {skill.name}\n{skill.description}\n\n{skill.body}"

    def _create_skill(self, args: dict[str, Any]) -> str:
        try:
            skill = self.skills.create_skill(
                name=args["name"],
                description=args["description"],
                body=args["body"],
                triggers=args.get("triggers") or [],
                source_session=self.session_id,
            )
        except FileExistsError as exc:
            return f"[error] {exc}"
        return f"created skill {skill.name!r}"
