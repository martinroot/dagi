import json
import time
from dataclasses import replace
from pathlib import Path
from http.cookiejar import CookieJar
from threading import Event, Thread
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import pytest

from dagi_core.auth import hash_password
from dagi_core.config import Config
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.usage import UsagePolicy
from dagi_core.web import WebApp


def _config(tmp_path):
    return Config(
        api_key="test-only-key",
        base_url="https://provider.invalid/v1",
        model="test-model",
        home=tmp_path / "home",
        workspace=tmp_path / "workspace",
        enable_shell=False,
        usage_policy=UsagePolicy(max_calls_per_run=8),
        compression_model="test-model",
        context_limit_tokens=8_000,
        context_max_tool_result_chars=1_000,
        max_delegation_depth=2,
        max_child_agents_per_run=3,
        web_username="admin",
        web_password_hash=hash_password("test-only-password", salt=b"0123456789abcdef", iterations=1_000),
        web_cookie_path="/",
        web_public_origin="",
        web_cookie_secure=False,
    )


def _create_session(config):
    state = StateStore(config.database)
    session_id = state.create_session("goal session")
    state.close()
    return session_id


def _wait_goal(config, goal_id, expected):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = StateStore(config.database)
        goal = state.get_goal(goal_id)
        state.close()
        if goal and goal["status"] == expected:
            return goal
        time.sleep(0.02)
    raise AssertionError(f"goal {goal_id} did not reach {expected}")


def _wait_goal_terminal(config, goal_id):
    terminal = {"completed", "capped", "limit", "error", "interrupted"}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = StateStore(config.database)
        goal = state.get_goal(goal_id)
        state.close()
        if goal and goal["status"] in terminal:
            return goal
        time.sleep(0.02)
    raise AssertionError(f"goal {goal_id} did not reach a terminal state")


class WriteResultProvider:
    model = "test-model"

    def __init__(self, workspace: Path, write_result: bool):
        self.workspace = workspace
        self.write_result = write_result

    def stream(self, _messages, _tools):
        if self.write_result:
            self.workspace.mkdir(parents=True, exist_ok=True)
            (self.workspace / "result.txt").write_text("ready", encoding="utf-8")
        yield StreamEvent(kind="text", text="The goal is complete.")
        yield StreamEvent(kind="finish", finish_reason="stop")


def test_goal_completes_only_after_all_checks_pass(tmp_path):
    config = _config(tmp_path)
    provider = WriteResultProvider(config.workspace, write_result=True)
    app = WebApp(config, lambda *_args: provider)
    session_id = _create_session(config)
    try:
        goal = app.start_goal(session_id, {
            "objective": "create a result",
            "checks": [{"type": "file_exists", "path": "result.txt"}],
            "max_iterations": 2,
        })
        completed = _wait_goal(config, goal["goal_id"], "completed")
        assert completed["iteration"] == 1
        assert completed["feedback"][0]["passed"] is True
        assert len(completed["runs"]) == 1
    finally:
        app.close()


def test_model_claim_cannot_complete_goal_when_check_fails(tmp_path):
    config = _config(tmp_path)
    provider = WriteResultProvider(config.workspace, write_result=False)
    app = WebApp(config, lambda *_args: provider)
    session_id = _create_session(config)
    try:
        goal = app.start_goal(session_id, {
            "objective": "create a result",
            "checks": [{"type": "file_exists", "path": "result.txt"}],
            "max_iterations": 1,
        })
        capped = _wait_goal(config, goal["goal_id"], "capped")
        assert capped["feedback"][0]["passed"] is False
        assert len(capped["runs"]) == 1
    finally:
        app.close()


def test_child_goal_check_uses_the_goal_owners_workspace(tmp_path):
    config = _config(tmp_path)
    provider = WriteResultProvider(config.workspace, write_result=False)
    app = WebApp(config, lambda *_args: provider)
    session_id = _create_session(config)
    root_result = config.workspace / "result.txt"
    root_result.parent.mkdir(parents=True, exist_ok=True)
    root_result.write_text("ready", encoding="utf-8")
    state = StateStore(config.database)
    state.set_session_workspace(session_id, ".dagi-children/goal-child")
    state.close()
    try:
        goal = app.start_goal(session_id, {
            "objective": "verify child result",
            "checks": [{"type": "file_exists", "path": "result.txt"}],
            "max_iterations": 1,
        })
        terminal = _wait_goal_terminal(config, goal["goal_id"])

        assert terminal["status"] == "capped"
        assert terminal["feedback"][0]["passed"] is False
        assert terminal["feedback"][0]["detail"] == "file is absent"
        assert len(terminal["runs"]) == 1
    finally:
        app.close()


def test_goal_rejects_an_owning_workspace_symlink_escape(tmp_path):
    config = _config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    child_root = config.workspace / ".dagi-children"
    child_root.mkdir(parents=True)
    (child_root / "escape").symlink_to(outside, target_is_directory=True)
    app = WebApp(config, lambda *_args: WriteResultProvider(config.workspace, write_result=False))
    session_id = _create_session(config)
    state = StateStore(config.database)
    state.set_session_workspace(session_id, ".dagi-children/escape")
    state.close()
    try:
        with pytest.raises(ValueError, match="workspace"):
            app.start_goal(session_id, {
                "objective": "must not inspect outside workspace",
                "checks": [{"type": "file_exists", "path": "result.txt"}],
                "max_iterations": 1,
            })
        state = StateStore(config.database)
        assert state.list_goals(session_id) == []
        state.close()
    finally:
        app.close()


def test_request_payload_cannot_enable_privileged_command_check(tmp_path):
    config = _config(tmp_path)
    app = WebApp(config, lambda *_args: WriteResultProvider(config.workspace, write_result=False))
    session_id = _create_session(config)
    try:
        with pytest.raises(ValueError, match="operator-configured"):
            app.start_goal(session_id, {
                "objective": "run a command",
                "checks": [{
                    "type": "command",
                    "argv": ["/usr/bin/touch", "should-not-run"],
                    "allow_commands": True,
                }],
                "max_iterations": 1,
                "enable_check_commands": True,
            })
        state = StateStore(config.database)
        assert state.list_goals(session_id) == []
        assert not (config.workspace / "should-not-run").exists()
        state.close()
    finally:
        app.close()


def test_goal_budget_is_shared_across_iterations(tmp_path):
    config = replace(_config(tmp_path), usage_policy=UsagePolicy(max_calls_per_run=1))
    provider = WriteResultProvider(config.workspace, write_result=False)
    app = WebApp(config, lambda *_args: provider)
    session_id = _create_session(config)
    try:
        goal = app.start_goal(session_id, {
            "objective": "create a result",
            "checks": [{"type": "file_exists", "path": "result.txt"}],
            "max_iterations": 3,
        })
        limited = _wait_goal(config, goal["goal_id"], "limit")
        assert limited["iteration"] == 1
        assert len(limited["runs"]) == 1
        state = StateStore(config.database)
        assert state.usage_summary_for_budget(limited["runs"][0])["provider_calls"] == 1
        state.close()
    finally:
        app.close()


class BlockingProvider:
    model = "test-model"

    def __init__(self):
        self.started = Event()
        self.cancelled = Event()

    def stream(self, _messages, _tools):
        self.started.set()
        while not self.cancelled.wait(0.01):
            pass
        yield StreamEvent(kind="finish", finish_reason="stop")

    def cancel(self):
        self.cancelled.set()


def test_interrupted_goal_can_be_resumed_explicitly(tmp_path):
    config = _config(tmp_path)
    blocking = BlockingProvider()
    factory_calls = 0

    def factory(*_args):
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            return blocking
        return WriteResultProvider(config.workspace, write_result=factory_calls >= 3)

    app = WebApp(config, factory)
    session_id = _create_session(config)
    try:
        goal = app.start_goal(session_id, {
            "objective": "create a result",
            "checks": [{"type": "file_exists", "path": "result.txt"}],
            "max_iterations": 2,
        })
        assert blocking.started.wait(3)
        app.control_goal(goal["goal_id"], "stop")
        interrupted = _wait_goal(config, goal["goal_id"], "interrupted")
        deadline = time.monotonic() + 3
        while goal["goal_id"] in app._goals and time.monotonic() < deadline:
            time.sleep(0.01)
        assert interrupted["iteration"] == 1

        app.control_goal(goal["goal_id"], "resume")
        completed = _wait_goal(config, goal["goal_id"], "completed")
        assert completed["iteration"] == 2
        assert len(completed["runs"]) == 2
    finally:
        app.close()


def _api_request(base, path, opener, *, method="GET", payload=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_goal_http_api_requires_session_and_rejects_payload_capability_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_WORKERS", "{}")
    config = replace(_config(tmp_path), web_public_origin="https://sandbox.example")
    config.workspace.mkdir(parents=True, exist_ok=True)
    (config.workspace / "ready.txt").write_text("ready", encoding="utf-8")
    app = WebApp(config, lambda *_args: WriteResultProvider(config.workspace, write_result=False))
    server = app.create_server(host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        try:
            with urlopen(base + "/api/sessions", timeout=5) as response:
                raise AssertionError(f"unauthenticated API unexpectedly returned {response.status}")
        except HTTPError as exc:
            assert exc.code == 401

        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        login = Request(
            base + "/api/auth/login",
            data=json.dumps({"username": "admin", "password": "test-only-password"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(login, timeout=5) as response:
            assert response.status == 200
        status, session = _api_request(base, "/api/sessions", opener, method="POST", payload={"title": "api-goal"})
        assert status == 201
        session_id = session["session_id"]

        status, error = _api_request(
            base,
            f"/api/sessions/{session_id}/goals",
            opener,
            method="POST",
            payload={
                "objective": "attempt command",
                "checks": [{"type": "command", "argv": ["/usr/bin/touch", "forbidden"]}],
                "max_iterations": 1,
                "enable_check_commands": True,
            },
        )
        assert status == 400 and "operator-configured" in error["error"]

        status, started = _api_request(
            base,
            f"/api/sessions/{session_id}/goals",
            opener,
            method="POST",
            payload={
                "objective": "verify existing file",
                "checks": [{"type": "file_exists", "path": "ready.txt"}],
                "max_iterations": 2,
            },
        )
        assert status == 202
        goal_id = started["goal_id"]
        completed = _wait_goal(config, goal_id, "completed")
        assert completed["iteration"] == 0
        status, detail = _api_request(base, f"/api/goals/{goal_id}", opener)
        assert status == 200 and detail["goal"]["status"] == "completed"

        status, _error = _api_request(
            base,
            f"/api/sessions/{session_id}/goals",
            opener,
            method="POST",
            payload={"objective": "csrf", "checks": [{"type": "file_exists", "path": "ready.txt"}]},
            origin="https://evil.example",
        )
        assert status == 403
        state = StateStore(config.database)
        assert len(state.list_goals(session_id)) == 1
        state.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
