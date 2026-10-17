import sys

import pytest

from dagi_core.goals import validate_checks, verify


def test_deterministic_file_checks_report_each_result(tmp_path):
    (tmp_path / "result.txt").write_text("approved output\n", encoding="utf-8")
    (tmp_path / "valid.json").write_text('{"ok":true}', encoding="utf-8")
    checks = [
        {"type": "file_exists", "path": "result.txt"},
        {"type": "file_contains", "path": "result.txt", "text": "approved"},
        {"type": "json_valid", "path": "valid.json"},
        {"type": "file_contains", "path": "result.txt", "text": "missing"},
    ]

    results = verify(tmp_path, checks)

    assert [item["passed"] for item in results] == [True, True, True, False]
    assert results[3]["detail"] == "expected text is absent"


def test_check_paths_cannot_escape_workspace(tmp_path):
    result = verify(tmp_path, [{"type": "file_exists", "path": "../outside.txt"}])
    assert result[0]["passed"] is False
    assert "workspace" in result[0]["detail"]

    result = verify(tmp_path, [{"type": "json_valid", "path": "../../etc/passwd"}])
    assert result[0]["passed"] is False
    assert "workspace" in result[0]["detail"]


def test_command_check_is_disabled_by_default_and_payload_cannot_enable_it(tmp_path):
    marker = tmp_path / "should-not-exist"
    command = [sys.executable, "-c", "from pathlib import Path; Path('should-not-exist').write_text('ran')"]

    result = verify(tmp_path, [{"type": "command", "argv": command}])
    assert result[0]["passed"] is False
    assert result[0]["detail"] == "command checks are disabled"
    assert not marker.exists()

    with pytest.raises(ValueError, match="unexpected"):
        validate_checks([{"type": "command", "argv": command, "allow_commands": True}])


def test_check_type_must_be_a_known_string():
    with pytest.raises(ValueError, match="unsupported acceptance check type"):
        validate_checks([{"type": [], "path": "x"}])


def test_operator_enabled_command_check_runs_without_shell(tmp_path):
    result = verify(tmp_path, [{
        "type": "command",
        "argv": [sys.executable, "-c", "print('deterministic-check')"],
    }], allow_commands=True)

    assert result[0]["passed"] is True
    assert "deterministic-check" in result[0]["detail"]["output"]


def test_check_limits_and_json_errors_are_deterministic(tmp_path):
    (tmp_path / "broken.json").write_text("not-json", encoding="utf-8")
    results = verify(tmp_path, [{"type": "json_valid", "path": "broken.json"}])
    assert results[0]["passed"] is False
    assert results[0]["detail"].startswith("JSONDecodeError:")
    with pytest.raises(ValueError, match="1..20"):
        validate_checks([])
    with pytest.raises(ValueError, match="1..20"):
        validate_checks([{"type": "file_exists", "path": "x"}] * 21)
