import os
from pathlib import Path

import pytest

from dagi_core.state import StateStore
from dagi_core.tools import Tool, ToolError, ToolRegistry, ToolResult


def make_tools(tmp_path: Path, *, shell=False, approve=None):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    return state, ToolRegistry(tmp_path / "workspace", state, session, shell_enabled=shell, approve_shell=approve)


def test_workspace_file_tools_roundtrip(tmp_path):
    state, tools = make_tools(tmp_path)

    tools.call("write_file", {"path": "notes/a.txt", "content": "hello"})

    assert "hello" in tools.call("read_file", {"path": "notes/a.txt"}).content
    assert "a.txt" in tools.call("list_dir", {"path": "notes"}).content
    state.close()


def test_read_file_returns_structured_path_size_line_count_and_truncation(tmp_path):
    state, tools = make_tools(tmp_path)
    path = tools.workspace / "notes" / "a.txt"
    path.parent.mkdir(parents=True)
    contents = "alpha\nbeta\n"
    path.write_text(contents, encoding="utf-8")

    result = tools.call("read_file", {"path": "notes/a.txt"})

    assert result.content == contents
    assert result.presentation == {
        "type": "file",
        "summary": "Read notes/a.txt",
        "artifacts": [{"path": "notes/a.txt", "operation": "read"}],
        "diagnostics": {"size_bytes": len(contents.encode("utf-8")), "line_count": 2, "truncated": False},
    }
    state.close()


def test_read_file_marks_truncated_preview_structurally(tmp_path):
    state, tools = make_tools(tmp_path)
    path = tools.workspace / "large.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = "line\n" * 2_000
    path.write_text(contents, encoding="utf-8")

    result = tools.call("read_file", {"path": "large.txt"})

    assert "[truncated" in result.content
    assert result.presentation["diagnostics"]["truncated"] is True
    assert result.presentation["diagnostics"]["line_count"] == 2_000
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


def test_public_registration_adds_custom_tool_without_changing_builtins(tmp_path):
    state, tools = make_tools(tmp_path)
    custom = Tool(
        name="custom_echo",
        description="Return the supplied value.",
        parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        handler=lambda args: ToolResult(f"custom: {args['value']}"),
    )

    tools.register(custom)
    result = tools.call("custom_echo", {"value": "ready"})

    assert result == ToolResult("custom: ready", is_error=False)
    assert "custom_echo" in {item.name for item in tools.specs()}
    assert {item.name for item in tools.specs()} >= {"read_file", "write_file", "custom_echo"}
    state.close()


def test_duplicate_public_tool_names_are_rejected(tmp_path):
    state, tools = make_tools(tmp_path)
    duplicate = Tool("read_file", "shadow", {"type": "object"}, lambda _args: "shadow")

    with pytest.raises(ValueError, match="already registered"):
        tools.register(duplicate)
    state.close()


def test_tool_presentation_metadata_is_bounded_and_json_serializable():
    with pytest.raises(ValueError, match="exceeds 16000 bytes"):
        ToolResult("text", presentation={"type": "custom", "diagnostics": {"payload": "x" * 16_000}})
    with pytest.raises(ValueError, match="only JSON values"):
        ToolResult("text", presentation={"type": "custom", "diagnostics": {"value": object()}})
    with pytest.raises(ValueError, match="unsupported fields"):
        ToolResult("text", presentation={"type": "custom", "html": "<script>"})


def test_tool_results_have_explicit_error_state(tmp_path):
    state, tools = make_tools(tmp_path)
    tools.register(Tool(
        "structured_error", "Return a structured failure.", {"type": "object"},
        lambda _args: ToolResult("not available", is_error=True),
    ))

    result = tools.call("structured_error", {})

    assert result.content == "not available"
    assert result.is_error is True
    state.close()


def test_write_file_recovery_verifier_confirms_only_exact_effect(tmp_path):
    state, tools = make_tools(tmp_path)
    args = {"path": "result.txt", "content": "expected"}

    assert tools.recovery_decision("write_file", args)[0] == "pending"
    tools.call("write_file", args)
    assert tools.recovery_decision("write_file", args)[0] == "succeeded"
    (tools.workspace / "result.txt").write_text("different")
    assert tools.recovery_decision("write_file", args)[0] == "uncertain"
    state.close()


def test_tool_recovery_policy_uses_retryability_and_effect_verifier(tmp_path):
    state, tools = make_tools(tmp_path)
    tools.register(Tool(
        "safe_retry", "Safe idempotent operation.", {"type": "object"},
        lambda _args: "done", retryable=True,
    ))
    tools.register(Tool(
        "verified", "Operation with effect check.", {"type": "object"},
        lambda _args: "done", verify_effect=lambda _args: True,
    ))
    tools.register(Tool(
        "unknown", "Operation with unknown effect.", {"type": "object"},
        lambda _args: "done", verify_effect=lambda _args: None,
    ))

    assert tools.recovery_decision("safe_retry", {})[0] == "pending"
    assert tools.recovery_decision("safe_retry", {}, persisted_retryable=False)[0] == "uncertain"
    assert tools.recovery_decision("verified", {})[0] == "succeeded"
    assert tools.recovery_decision("unknown", {})[0] == "uncertain"
    state.close()


@pytest.mark.skipif(os.name != "posix", reason="shell command smoke test is POSIX-only")
def test_shell_runs_only_after_positive_approval(tmp_path):
    state, tools = make_tools(tmp_path, shell=True, approve=lambda command: command == "printf approved")

    result = tools.call("run_bash", {"command": "printf approved"})

    assert "exit_code=0" in result.content
    assert result.content.strip().endswith("approved")
    state.close()
