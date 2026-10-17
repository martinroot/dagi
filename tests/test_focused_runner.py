import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "test-focused.sh"


def _fake_runner(path: Path, marker_env: str, exit_env: str) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open(os.environ[{marker_env!r}], 'w').write(json.dumps(sys.argv[1:]))\n"
        f"raise SystemExit(int(os.environ.get({exit_env!r}, '0')))\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.mark.skipif(os.name != "posix", reason="focused runner uses a Bash script")
def test_focused_runner_runs_selected_python_and_node_commands(tmp_path):
    python_runner = tmp_path / "fake-python"
    node_runner = tmp_path / "fake-node"
    python_marker = tmp_path / "python-args.json"
    node_marker = tmp_path / "node-args.json"
    _fake_runner(python_runner, "PYTHON_MARKER", "PYTHON_EXIT")
    _fake_runner(node_runner, "NODE_MARKER", "NODE_EXIT")
    env = os.environ | {
        "PYTHON_MARKER": str(python_marker),
        "NODE_MARKER": str(node_marker),
        "DAGI_TEST_NODE": str(node_runner),
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "--python", str(python_runner), "--node-pattern", "file renderer",
         "tests/test_core_tools.py::test_read_file_returns_structured_path_size_line_count_and_truncation"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pytest passed" in result.stderr
    assert "Node UI passed" in result.stderr
    assert json.loads(python_marker.read_text()) == [
        "-m", "pytest", "tests/test_core_tools.py::test_read_file_returns_structured_path_size_line_count_and_truncation",
        "-q", "--tb=short",
    ]
    assert json.loads(node_marker.read_text()) == [
        "--test", "--test-name-pattern=file renderer", "tests/test_core_web_ui.js",
    ]


@pytest.mark.skipif(os.name != "posix", reason="focused runner uses a Bash script")
def test_focused_runner_reports_failures_from_both_commands(tmp_path):
    python_runner = tmp_path / "fake-python"
    node_runner = tmp_path / "fake-node"
    _fake_runner(python_runner, "PYTHON_MARKER", "PYTHON_EXIT")
    _fake_runner(node_runner, "NODE_MARKER", "NODE_EXIT")
    env = os.environ | {
        "PYTHON_MARKER": str(tmp_path / "python-args.json"),
        "NODE_MARKER": str(tmp_path / "node-args.json"),
        "DAGI_TEST_NODE": str(node_runner),
        "PYTHON_EXIT": "4",
        "NODE_EXIT": "5",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "--python", str(python_runner), "--node-pattern", "example",
         "tests/test_core_tools.py::test_read_file_returns_structured_path_size_line_count_and_truncation"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
    )

    assert result.returncode == 1
    assert "pytest failed (exit 4)" in result.stderr
    assert "Node UI failed (exit 5)" in result.stderr
