"""Operator approval for privileged commands started from a chat session.

A chat session may ask to run a shell command. The command does not start
until an operator approves it in the browser, and the run waits for that
decision. Nothing is executed without a recorded, explicit answer.
"""
from __future__ import annotations

import threading
import time
from uuid import uuid4

DEFAULT_TIMEOUT_SECONDS = 300
MAX_PENDING = 32
MAX_COMMAND_CHARS = 4000


class ApprovalRegistry:
    """Pending command approvals, resolved by the operator in the browser."""

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        if timeout_seconds < 1 or timeout_seconds > 3600:
            raise ValueError("approval timeout must be 1..3600 seconds")
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}

    def _expire(self) -> None:
        now = time.monotonic()
        for approval_id, item in list(self._pending.items()):
            if item["expires_at"] <= now:
                self._pending.pop(approval_id, None)
                item["event"].set()
                item["approved"] = False

    def request(self, command: str, *, session_id: int | None = None, run_id: str | None = None) -> bool:
        """Register a command and wait for the operator's decision."""
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be nonempty text")
        if len(command) > MAX_COMMAND_CHARS:
            raise ValueError(f"command must be at most {MAX_COMMAND_CHARS} characters")
        with self._lock:
            self._expire()
            if len(self._pending) >= MAX_PENDING:
                raise ValueError("too many commands are waiting for approval")
            approval_id = uuid4().hex
            item = {
                "id": approval_id,
                "command": command,
                "session_id": session_id,
                "run_id": run_id,
                "created_at": time.time(),
                "expires_at": time.monotonic() + self.timeout_seconds,
                "event": threading.Event(),
                "approved": False,
            }
            self._pending[approval_id] = item
        item["event"].wait(self.timeout_seconds)
        with self._lock:
            self._pending.pop(approval_id, None)
        return bool(item["approved"])

    def pending(self) -> list[dict]:
        with self._lock:
            self._expire()
            return [
                {
                    "id": item["id"],
                    "command": item["command"],
                    "session_id": item["session_id"],
                    "run_id": item["run_id"],
                    "created_at": item["created_at"],
                    "expires_in": max(0, int(item["expires_at"] - time.monotonic())),
                }
                for item in self._pending.values()
            ]

    def decide(self, approval_id: str, approved: bool) -> bool:
        """Record the operator's answer and release the waiting run."""
        with self._lock:
            item = self._pending.get(approval_id)
            if item is None:
                return False
            item["approved"] = bool(approved)
            item["event"].set()
            return True
