import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dagi_core.auth import hash_password
from dagi_core.config import Config
from dagi_core.state import StateStore
from dagi_core.usage import UsagePolicy
from dagi_core.web import WebApp


def _config(root, token, origin=""):
    return Config(
        api_key="test-only-key",
        base_url="https://provider.invalid/v1",
        model="test-model",
        home=root / "home",
        workspace=root / "workspace",
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
        web_public_origin=origin,
        web_cookie_secure=False,
        web_token=token,
    )


def _start(app):
    server = app.create_server(host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def _request(base, path, *, method="GET", payload=None, token=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_authenticated_worker_list_and_proxy_keep_peer_tokens_server_side(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DAGI_WORKERS", "{}")
    workers = []
    servers = []
    try:
        for name in ("alpha", "beta"):
            app = WebApp(_config(tmp_path / name, f"{name}-private-token"))
            server, thread, base = _start(app)
            workers.append((name, app, base, f"{name}-private-token"))
            servers.append((server, thread))

        monkeypatch.setenv("DAGI_WORKERS", json.dumps({
            name: {"url": base, "token": token}
            for name, _app, base, token in workers
        }))
        hub = WebApp(_config(tmp_path / "hub", "hub-private-token", "https://sandbox.example"))
        assert "hub-private-token" not in repr(hub.config)
        hub_server, hub_thread, hub_base = _start(hub)
        servers.append((hub_server, hub_thread))

        assert _request(hub_base, "/api/workers")[0] == 401
        status, listing = _request(hub_base, "/api/workers", token="hub-private-token")
        assert status == 200
        assert {entry["id"] for entry in listing["workers"]} == {"alpha", "beta"}
        listing_text = json.dumps(listing)
        assert "alpha-private-token" not in listing_text
        assert "beta-private-token" not in listing_text
        assert "hub-private-token" not in listing_text
        assert "alpha-private-token" not in repr(hub.workers)

        for name, worker_app, worker_base, worker_token in workers:
            worker_app.config.workspace.mkdir(parents=True, exist_ok=True)
            (worker_app.config.workspace / "ready.txt").write_text("ready", encoding="utf-8")
            status, health = _request(
                hub_base, f"/api/workers/{name}/proxy/api/health", token="hub-private-token"
            )
            assert status == 200 and health["healthy"] is True
            status, receipt = _request(
                hub_base,
                f"/api/workers/{name}/proxy/api/sessions",
                method="POST",
                payload={"title": f"created-on-{name}"},
                token="hub-private-token",
            )
            assert status == 200 and isinstance(receipt["session_id"], int)
            status, goal = _request(
                hub_base,
                f"/api/workers/{name}/proxy/api/sessions/{receipt['session_id']}/goals",
                method="POST",
                payload={
                    "objective": "check ready file",
                    "checks": [{"type": "file_exists", "path": "ready.txt"}],
                    "max_iterations": 1,
                },
                token="hub-private-token",
            )
            assert status == 200 and "goal_id" in goal
            status, detail = _request(
                hub_base, f"/api/workers/{name}/proxy/api/goals/{goal['goal_id']}",
                token="hub-private-token",
            )
            assert status == 200 and detail["goal"]["status"] in {"running", "completed"}
            assert _request(worker_base, "/api/health")[0] == 401
            assert _request(worker_base, "/api/health", token=worker_token)[0] == 200

        status, error = _request(
            hub_base,
            "/api/workers/alpha/proxy/api/sessions/999999",
            token="hub-private-token",
        )
        assert status == 502
        error_text = json.dumps(error)
        assert "alpha-private-token" not in error_text
        assert "hub-private-token" not in error_text

        status, error = _request(
            hub_base,
            "/api/workers/alpha/proxy/api/sessions",
            method="POST",
            payload={"title": "cross-origin-must-not-write"},
            token="hub-private-token",
            origin="https://evil.example",
        )
        assert status == 403 and "token" not in json.dumps(error).lower()

        for _name, app, _base, _token in workers:
            state = StateStore(app.config.database)
            titles = {item["title"] for item in state.list_sessions(20)}
            state.close()
            assert f"created-on-{_name}" in titles
            assert "cross-origin-must-not-write" not in titles
    finally:
        for server, thread in reversed(servers):
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
    captured = capsys.readouterr()
    logs = captured.out + captured.err
    assert "hub-private-token" not in logs
    assert "alpha-private-token" not in logs
    assert "beta-private-token" not in logs
