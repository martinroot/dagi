import sys
from pathlib import Path
import threading
import time

import pytest

from dagi_core.execution import execute


def test_execution_does_not_inherit_service_credentials(tmp_path, monkeypatch):
    secret = "must-not-enter-child-process"
    monkeypatch.setenv("DAGI_API_KEY", secret)
    monkeypatch.setenv("DAGI_WEB_TOKEN", secret)
    monkeypatch.setenv("DAGI_WORKERS", secret)
    code = (
        "import json,os; print(json.dumps({k:os.environ.get(k) for k in "
        "('DAGI_API_KEY','DAGI_WEB_TOKEN','DAGI_WORKERS')}))"
    )
    result = execute([sys.executable, "-c", code], tmp_path)
    assert result["passed"]
    assert secret not in result["output"]
    assert 'null' in result["output"]


def test_execution_requires_argv_and_never_uses_shell(tmp_path):
    with pytest.raises(ValueError, match="argv"):
        execute("printf unsafe", tmp_path)
    with pytest.raises(ValueError, match="argv"):
        execute(["/usr/bin/printf", ""], tmp_path)


def test_execution_timeout_kills_process_group_and_caps_output(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    child_code = (
        "import subprocess,sys,time,pathlib; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    )
    result = execute([sys.executable, "-c", child_code, str(child_pid_file)], tmp_path, timeout=0.2)
    assert result["reason"] == "timeout" and not result["passed"]
    child_pid = int(child_pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{child_pid}/stat").read_text(encoding="ascii").split()[2]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state == "Z":
            break
        time.sleep(0.02)
    else:
        pytest.fail("timed-out command left its child process running")

    output = execute([sys.executable, "-c", "print('x' * 100000)"], tmp_path)
    assert output["passed"]
    assert len(output["output"]) <= 8_020
    assert "output truncated" in output["output"]


def test_execution_cancellation_kills_process_group(tmp_path):
    cancellation = threading.Event()
    results = []
    thread = threading.Thread(
        target=lambda: results.append(
            execute([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path,
                    timeout=10, cancellation=cancellation)
        ),
        daemon=True,
    )
    thread.start()
    time.sleep(0.1)
    cancellation.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert results[0]["reason"] == "cancelled"
    assert not results[0]["passed"]
