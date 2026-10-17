"""Run explicitly enabled goal checks with bounded output and cleanup.

This is not an OS sandbox: opted-in checks run with the Dagi service user's
filesystem permissions. The subprocess receives a fixed, credential-free env.
"""
from __future__ import annotations

import math
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Event
from typing import Any

_MAX_OUTPUT_BYTES = 8_000
_MAX_TIMEOUT_SECONDS = 300
_CHECK_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
}


def execute(
    argv: list[str],
    cwd: str | Path,
    *,
    timeout: float = 30,
    cancellation: Event | None = None,
) -> dict[str, Any]:
    """Run an argv vector without a shell, inheriting no service environment."""
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 50
        or any(not isinstance(item, str) or not item for item in argv)
        or sum(len(item.encode("utf-8")) for item in argv) > 64_000
    ):
        raise ValueError("command check requires a non-empty argv list of at most 50 arguments")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= _MAX_TIMEOUT_SECONDS:
        raise ValueError(f"command timeout must be in (0, {_MAX_TIMEOUT_SECONDS}] seconds")
    working_dir = Path(cwd).expanduser().resolve()
    if not working_dir.is_dir():
        raise ValueError("command working directory must exist")
    if cancellation is not None and cancellation.is_set():
        return {"exit_code": None, "output": "", "reason": "cancelled", "passed": False}

    with tempfile.TemporaryFile(mode="w+b") as output:
        process = subprocess.Popen(
            argv,
            cwd=working_dir,
            env=_CHECK_ENV.copy(),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=(os.name == "posix"),
        )
        deadline = time.monotonic() + float(timeout)
        reason = ""
        try:
            while process.poll() is None:
                if cancellation is not None and cancellation.is_set():
                    reason = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    reason = "timeout"
                    break
                time.sleep(0.02)
        finally:
            if process.poll() is None:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.wait()

        output.seek(0)
        raw = output.read(_MAX_OUTPUT_BYTES + 1)
        text = raw[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        if len(raw) > _MAX_OUTPUT_BYTES:
            text += "\n[output truncated]"
        return {
            "exit_code": process.returncode,
            "output": text,
            "reason": reason,
            "passed": not reason and process.returncode == 0,
        }
