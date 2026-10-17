import pytest
from threading import Thread

from dagi_core.auth import hash_password
from dagi_core.config import Config
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


def _start(app):
    server = app.create_server(host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_only_one_web_runtime_owns_a_dagi_home_and_lease_releases(tmp_path):
    config = _config(tmp_path)
    first = _start(WebApp(config))
    try:
        with pytest.raises(ValueError, match="another Dagi runtime"):
            WebApp(config).create_server(host="127.0.0.1", port=0)
    finally:
        _stop(*first)

    second = _start(WebApp(config))
    _stop(*second)


def test_server_start_recovers_stale_runs_and_goals(tmp_path):
    config = _config(tmp_path)
    state = StateStore(config.database)
    session_id = state.create_session("interrupted")
    run_id = state.create_run(session_id)
    goal_id = state.create_goal(
        session_id, "complete after restart", [{"type": "file_exists", "path": "result.txt"}], 2
    )
    state.close()

    server, thread = _start(WebApp(config))
    try:
        state = StateStore(config.database)
        assert state.get_run(run_id)["status"] == "error"
        assert state.get_goal(goal_id)["status"] == "interrupted"
        state.close()
    finally:
        _stop(server, thread)
