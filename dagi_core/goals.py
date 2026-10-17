"""Deterministic, bounded goal acceptance checks."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from typing import Any

from .execution import execute
from .tools import _resolve

_MAX_CHECK_FILE_BYTES = 2_000_000
_MAX_CHECKS = 20
_MAX_PATH_CHARS = 4096
_MAX_TEXT_CHARS = 64_000


def validate_checks(checks: Any) -> list[dict[str, Any]]:
    if not isinstance(checks, list) or not 1 <= len(checks) <= _MAX_CHECKS:
        raise ValueError(f"a goal requires 1..{_MAX_CHECKS} acceptance checks")
    validated: list[dict[str, Any]] = []
    allowed_fields = {
        "file_exists": {"type", "path"},
        "file_contains": {"type", "path", "text"},
        "json_valid": {"type", "path"},
        "command": {"type", "argv"},
    }
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("unsupported acceptance check type")
        check_type = check.get("type")
        if not isinstance(check_type, str) or check_type not in allowed_fields:
            raise ValueError("unsupported acceptance check type")
        extra = set(check) - allowed_fields[check_type]
        missing = allowed_fields[check_type] - set(check)
        if extra:
            raise ValueError(f"unexpected acceptance check fields: {sorted(extra)}")
        if missing:
            raise ValueError(f"missing acceptance check fields: {sorted(missing)}")
        if check_type == "command":
            argv = check["argv"]
            if (
                not isinstance(argv, list)
                or not 1 <= len(argv) <= 50
                or any(not isinstance(item, str) or not item for item in argv)
                or sum(len(item.encode("utf-8")) for item in argv) > 64_000
            ):
                raise ValueError("command check requires a non-empty argv list of at most 50 arguments")
        else:
            path = check["path"]
            if not isinstance(path, str) or not path.strip() or "\x00" in path or len(path) > _MAX_PATH_CHARS:
                raise ValueError("check path must be non-empty text of at most 4096 characters")
            if check_type == "file_contains":
                text = check["text"]
                if not isinstance(text, str) or not text or len(text) > _MAX_TEXT_CHARS:
                    raise ValueError("file_contains text must be non-empty and at most 64000 characters")
        validated.append(dict(check))
    return validated


def verify(
    workspace: Path,
    checks: Any,
    *,
    allow_commands: bool = False,
    cancellation: Event | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(allow_commands, bool):
        raise ValueError("allow_commands is an operator configuration value")
    root = Path(workspace).expanduser().resolve()
    results: list[dict[str, Any]] = []
    for check in validate_checks(checks):
        passed = False
        detail: Any = ""
        try:
            if cancellation is not None and cancellation.is_set():
                detail = "cancelled"
            elif check["type"] == "command":
                if not allow_commands:
                    detail = "command checks are disabled"
                else:
                    detail = execute(check["argv"], root, timeout=30, cancellation=cancellation)
                    passed = detail["passed"]
            else:
                path = _resolve(root, check["path"])
                if not path.is_file():
                    detail = "file is absent"
                elif check["type"] == "file_exists":
                    passed = True
                else:
                    with path.open("rb") as source:
                        raw = source.read(_MAX_CHECK_FILE_BYTES + 1)
                    if len(raw) > _MAX_CHECK_FILE_BYTES:
                        detail = "check input exceeds 2 MB"
                    else:
                        text = raw.decode("utf-8")
                        if check["type"] == "file_contains":
                            passed = check["text"] in text
                            if not passed:
                                detail = "expected text is absent"
                        else:
                            json.loads(text)
                            passed = True
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
        results.append({"check": check, "passed": passed, "detail": detail})
    return results
