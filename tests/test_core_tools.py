import os
from pathlib import Path

import pytest

from dagi_core.state import StateStore
from dagi_core.tools import ToolError, ToolRegistry


def make_tools(tmp_path: Path, *, shell=False, approve=None):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    return state, ToolRegistry(tmp_path / "workspace", state, session, shell_enabled=shell, approve_shell=approve)


def test_workspace_file_tools_roundtrip(tmp_path):
    state, tools = make_tools(tmp_path)

    tools.call("write_file", {"path": "notes/a.txt", "content": "hello"})

    assert "hello" in tools.call("read_file", {"path": "notes/a.txt"})
    assert "a.txt" in tools.call("list_dir", {"path": "notes"})
    state.close()


def test_file_tools_reject_paths_outside_workspace(tmp_path):
    state, tools = make_tools(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not read")
    link = tools.workspace / "escape.txt"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)

    with pytest.raises(ToolError, match="outside workspace"):
        tools.call("read_file", {"path": "escape.txt"})
    state.close()


def test_shell_is_absent_by_default_and_denied_without_approval(tmp_path):
    state, tools = make_tools(tmp_path)
    assert "run_bash" not in {spec.name for spec in tools.specs()}
    state.close()

    seen = []
    state, tools = make_tools(tmp_path / "denied", shell=True, approve=lambda command: seen.append(command) or False)
    with pytest.raises(ToolError, match="declined"):
        tools.call("run_bash", {"command": "touch must-not-exist"})
    assert seen == ["touch must-not-exist"]
    assert not (tools.workspace / "must-not-exist").exists()
    state.close()


@pytest.mark.skipif(os.name != "posix", reason="shell command smoke test is POSIX-only")
def test_shell_runs_only_after_positive_approval(tmp_path):
    state, tools = make_tools(tmp_path, shell=True, approve=lambda command: command == "printf approved")

    result = tools.call("run_bash", {"command": "printf approved"})

    assert "exit_code=0" in result
    assert result.strip().endswith("approved")
    state.close()
