import threading
import time

import pytest

from dagi_core.approvals import ApprovalRegistry


def test_a_command_waits_for_the_operator_decision():
    registry = ApprovalRegistry(timeout_seconds=5)
    result = {}

    def run():
        result["approved"] = registry.request("ssh -i key user@host 'uname -a'", session_id=1, run_id="r1")

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 2
    pending = []
    while time.monotonic() < deadline:
        pending = registry.pending()
        if pending:
            break
        time.sleep(0.01)
    assert pending, "the waiting command must be visible to the operator"
    assert pending[0]["command"].startswith("ssh")
    assert pending[0]["session_id"] == 1
    assert registry.decide(pending[0]["id"], True) is True
    worker.join(timeout=5)
    assert result["approved"] is True
    assert registry.pending() == []


def test_a_denied_command_is_not_executed():
    registry = ApprovalRegistry(timeout_seconds=5)
    result = {}

    def run():
        result["approved"] = registry.request("rm -rf /", session_id=1)

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not registry.pending():
        time.sleep(0.01)
    approval_id = registry.pending()[0]["id"]
    assert registry.decide(approval_id, False) is True
    worker.join(timeout=5)
    assert result["approved"] is False


def test_an_unknown_or_already_decided_approval_is_reported():
    registry = ApprovalRegistry(timeout_seconds=5)
    assert registry.decide("does-not-exist", True) is False


def test_an_expired_approval_denies_the_command():
    registry = ApprovalRegistry(timeout_seconds=1)
    started = time.monotonic()
    approved = registry.request("sleep 100")
    assert approved is False
    assert time.monotonic() - started < 10, "an expired approval must not block the run for long"


def test_only_bounded_commands_are_accepted():
    registry = ApprovalRegistry(timeout_seconds=1)
    with pytest.raises(ValueError):
        registry.request("")
    with pytest.raises(ValueError):
        registry.request("x" * 5000)
