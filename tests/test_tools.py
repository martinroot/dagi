from pathlib import Path

import pytest

from hermes.agent.tools import ToolExecutionError, ToolRegistry
from hermes.memory.store import MemoryStore
from hermes.skills.manager import SkillManager


def make_registry(
    tmp_path: Path, *, enable_shell: bool = False, approve_shell=None
) -> ToolRegistry:
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    skills = SkillManager(tmp_path / "skills")
    session_id = memory.create_session()
    return ToolRegistry(
        workspace=tmp_path,
        memory=memory,
        skills=skills,
        session_id=session_id,
        enable_shell=enable_shell,
        approve_shell=approve_shell,
    )


def test_write_then_read_file(tmp_path: Path):
    registry = make_registry(tmp_path)
    registry.call("write_file", {"path": "notes/todo.md", "content": "buy milk"})
    result = registry.call("read_file", {"path": "notes/todo.md"})
    assert "buy milk" in result


def test_list_dir(tmp_path: Path):
    registry = make_registry(tmp_path)
    registry.call("write_file", {"path": "a.txt", "content": "x"})
    result = registry.call("list_dir", {"path": "."})
    assert "a.txt" in result


def test_path_traversal_outside_workspace_is_rejected(tmp_path: Path):
    registry = make_registry(tmp_path)
    with pytest.raises(ToolExecutionError):
        registry.call("read_file", {"path": "../../etc/passwd"})


def test_shell_is_not_exposed_by_default(tmp_path: Path):
    registry = make_registry(tmp_path)
    assert "run_bash" not in {spec.name for spec in registry.specs()}


def test_run_bash_requires_explicit_approval(tmp_path: Path):
    registry = make_registry(tmp_path, enable_shell=True, approve_shell=lambda _: False)
    with pytest.raises(ToolExecutionError, match="declined"):
        registry.call("run_bash", {"command": "touch should-not-exist"})
    assert not (tmp_path / "should-not-exist").exists()


def test_run_bash_executes_in_workspace_after_approval(tmp_path: Path):
    registry = make_registry(tmp_path, enable_shell=True, approve_shell=lambda _: True)
    (tmp_path / "marker.txt").write_text("hi")
    result = registry.call("run_bash", {"command": "ls"})
    assert "exit_code=0" in result
    assert "marker.txt" in result


def test_bash_approval_receives_exact_command(tmp_path: Path):
    seen = []
    registry = make_registry(tmp_path, enable_shell=True, approve_shell=seen.append)
    with pytest.raises(ToolExecutionError, match="declined"):
        registry.call("run_bash", {"command": "echo KEEP_LITERAL"})
    assert seen == ["echo KEEP_LITERAL"]


def test_skill_create_list_use_roundtrip(tmp_path: Path):
    registry = make_registry(tmp_path)
    created = registry.call(
        "create_skill",
        {
            "name": "greet",
            "description": "say hi",
            "body": "just say hi",
            "triggers": ["hello"],
        },
    )
    assert "greet" in created

    listing = registry.call("list_skills", {})
    assert "greet" in listing

    used = registry.call("use_skill", {"name": "greet"})
    assert "just say hi" in used


def test_search_memory_returns_no_matches_message(tmp_path: Path):
    registry = make_registry(tmp_path)
    result = registry.call("search_memory", {"query": "anything"})
    assert result == "(no matches)"
