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


def test_builtin_arguments_reject_missing_and_wrong_typed_values_before_side_effects(tmp_path):
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError, match="missing required argument 'path'"):
        tools.call("read_file", {})
    with pytest.raises(ToolError, match="argument 'path' must be string"):
        tools.call("read_file", {"path": None})
    with pytest.raises(ToolError, match="argument 'content' must be string"):
        tools.call("write_file", {"path": "must-not-exist.txt", "content": 7})

    assert not (tools.workspace / "must-not-exist.txt").exists()
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


def test_write_file_reports_created_and_updated_artifact_metadata(tmp_path):
    state, tools = make_tools(tmp_path)

    created = tools.call("write_file", {"path": "notes/a.txt", "content": "first"})
    updated = tools.call("write_file", {"path": "notes/a.txt", "content": "second"})

    assert created.content == "saved notes/a.txt (5 chars)"
    assert created.presentation == {
        "type": "file",
        "summary": "Created notes/a.txt",
        "artifacts": [{"path": "notes/a.txt", "operation": "create"}],
        "diagnostics": {"size_bytes": 5, "created": True, "diff_available": False, "diff_truncated": False, "diff_reason": "new file"},
    }
    assert updated.presentation["summary"] == "Updated notes/a.txt"
    assert updated.presentation["artifacts"][0]["operation"] == "update"
    assert updated.presentation["diagnostics"]["created"] is False
    state.close()


def test_write_file_returns_bounded_unified_diff_for_small_text_update(tmp_path):
    state, tools = make_tools(tmp_path)
    target = tools.workspace / "notes" / "release.md"
    target.parent.mkdir(parents=True)
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    result = tools.call("write_file", {"path": "notes/release.md", "content": "alpha\ngamma\n"})

    assert result.presentation is not None
    artifact = result.presentation["artifacts"][0]
    assert artifact["operation"] == "update"
    assert artifact["diff"].startswith("--- a/notes/release.md\n+++ b/notes/release.md\n")
    assert "-beta\n" in artifact["diff"]
    assert "+gamma\n" in artifact["diff"]
    assert result.presentation["diagnostics"]["diff_available"] is True
    assert result.presentation["diagnostics"]["diff_truncated"] is False
    state.close()


def test_write_file_skips_diff_when_prior_file_exceeds_source_limit(tmp_path):
    state, tools = make_tools(tmp_path)
    target = tools.workspace / "large.txt"
    target.write_text("x" * 4_097, encoding="utf-8")

    result = tools.call("write_file", {"path": "large.txt", "content": "replacement"})

    assert result.presentation is not None
    assert "diff" not in result.presentation["artifacts"][0]
    assert result.presentation["diagnostics"]["diff_available"] is False
    assert result.presentation["diagnostics"]["diff_reason"] == "previous file exceeds 4096 bytes"
    state.close()


def test_list_dir_returns_structured_entries_without_changing_text(tmp_path):
    state, tools = make_tools(tmp_path)
    (tools.workspace / "docs").mkdir(parents=True)
    (tools.workspace / "docs" / "readme.md").write_text("notes", encoding="utf-8")
    (tools.workspace / "docs" / "nested").mkdir()

    result = tools.call("list_dir", {"path": "docs"})

    assert result.content == "nested/\nreadme.md"
    assert result.presentation == {
        "type": "directory",
        "summary": "Listed docs",
        "artifacts": [
            {"name": "nested", "path": "docs/nested", "kind": "directory"},
            {"name": "readme.md", "path": "docs/readme.md", "kind": "file"},
        ],
        "diagnostics": {"entry_count": 2, "empty": False},
    }
    state.close()


def test_search_memory_returns_structured_hits_with_source(tmp_path):
    state, tools = make_tools(tmp_path)
    message_id = state.append_message(tools.session_id, {"role": "user", "content": "needle in a remembered message"})

    result = tools.call("search_memory", {"query": "needle"})

    assert "[needle] in a remembered message" in result.content
    assert result.presentation["type"] == "memory"
    assert len(result.presentation["artifacts"]) == 1
    hit = result.presentation["artifacts"][0]
    assert hit["message_id"] == message_id
    assert hit["session_id"] == tools.session_id
    assert hit["role"] == "user"
    assert hit["snippet"] == "[needle] in a remembered message"
    assert isinstance(hit["created_at"], str)
    assert result.presentation["diagnostics"]["match_count"] == 1
    state.close()


def test_list_skills_returns_structured_skill_records(tmp_path):
    state, tools = make_tools(tmp_path)
    skill = state.create_skill("release-check", "Verify releases", ["release", "tag"], "1. run tests")
    state.record_skill_use(skill["name"])

    result = tools.call("list_skills", {})

    assert result.content == "- release-check: Verify releases"
    assert result.presentation == {
        "type": "skills",
        "summary": "Listed 1 skill",
        "artifacts": [{
            "name": "release-check", "description": "Verify releases",
            "triggers": ["release", "tag"], "use_count": 1,
        }],
        "diagnostics": {"skill_count": 1, "displayed_count": 1, "omitted_count": 0},
    }
    state.close()


def test_use_skill_returns_structured_loaded_skill_metadata(tmp_path):
    state, tools = make_tools(tmp_path)
    state.create_skill("release-check", "Verify releases", ["release", "tag"], "1. run tests")

    result = tools.call("use_skill", {"name": "release-check"})

    assert result.content == "# release-check\nVerify releases\n\n1. run tests"
    assert result.presentation is not None
    assert result.presentation == {
        "type": "skill",
        "summary": "Loaded skill release-check",
        "artifacts": [{
            "name": "release-check", "description": "Verify releases",
            "triggers": ["release", "tag"], "use_count": 1,
        }],
        "diagnostics": {"body_bytes": len("1. run tests")},
    }
    state.close()


def test_create_skill_returns_structured_metadata_without_body(tmp_path):
    state, tools = make_tools(tmp_path)

    result = tools.call("create_skill", {
        "name": "Release Review", "description": "Review a release", "triggers": ["tag"],
        "body": "1. verify changelog\n2. run tests",
    })

    assert result.content == "saved skill 'release-review'"
    assert result.presentation is not None
    assert result.presentation == {
        "type": "skill_created",
        "summary": "Created skill release-review",
        "artifacts": [{
            "name": "release-review", "description": "Review a release",
            "triggers": ["tag"], "use_count": 0,
        }],
        "diagnostics": {"body_bytes": len("1. verify changelog\n2. run tests")},
    }
    assert "body" not in result.presentation["artifacts"][0]
    state.close()


def test_list_skills_bounds_structured_metadata_for_large_catalog(tmp_path):
    state, tools = make_tools(tmp_path)
    for index in range(25):
        state.create_skill(
            f"skill-{index}", "d" * 800, ["trigger" * 20] * 10, "procedure",
        )

    result = tools.call("list_skills", {})

    assert result.presentation is not None
    assert result.presentation["diagnostics"] == {
        "skill_count": 25, "displayed_count": 20, "omitted_count": 5,
    }
    assert len(result.presentation["artifacts"]) == 20
    assert all(len(skill["description"]) <= 256 for skill in result.presentation["artifacts"])
    assert all(len(skill["triggers"]) <= 5 for skill in result.presentation["artifacts"])
    assert all(len(trigger) <= 80 for skill in result.presentation["artifacts"] for trigger in skill["triggers"])
    state.close()


def test_approved_shell_command_returns_structured_execution_metadata(tmp_path):
    state, tools = make_tools(tmp_path, shell=True, approve=lambda _command: True)

    result = tools.call("run_bash", {"command": "printf 'hello'; exit 7"})

    assert result.content == "exit_code=7\nhello"
    assert result.presentation is not None
    assert result.presentation["type"] == "command"
    assert result.presentation["summary"] == "Exited with code 7"
    assert result.presentation["artifacts"] == [{"exit_code": 7, "timed_out": False}]
    assert result.presentation["diagnostics"]["output_truncated"] is False
    assert result.presentation["diagnostics"]["operator_approved"] is True
    assert result.presentation["diagnostics"]["execution_boundary"] == "service-user host permissions; not an OS sandbox"
    assert isinstance(result.presentation["diagnostics"]["duration_ms"], int)
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
