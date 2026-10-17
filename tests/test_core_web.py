from concurrent.futures import ThreadPoolExecutor
import json
import time
from threading import Event, Thread
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from dagi_core.auth import hash_password
from dagi_core.config import Config
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.usage import UsagePolicy
from dagi_core.web import WebApp


def _config(tmp_path):
    return Config(
        api_key="placeholder-for-test",
        base_url="https://api.example/v1",
        model="main-model",
        home=tmp_path / "home",
        workspace=tmp_path / "workspace",
        enable_shell=False,
        usage_policy=UsagePolicy(max_calls_per_run=8),
        compression_model="summary-model",
        context_limit_tokens=8_000,
        context_max_tool_result_chars=1_000,
        max_delegation_depth=2,
        max_child_agents_per_run=3,
        web_username="admin",
        web_password_hash=hash_password("local-test-password", salt=b"0123456789abcdef", iterations=1_000),
        web_cookie_path="/",
        web_public_origin="",
        web_cookie_secure=False,
    )


_test_openers = {}


def _request(base, method="GET", payload=None):
    parsed = urlparse(base)
    if parsed.path.startswith("/api/") and "/api/auth/" not in parsed.path:
        opener = _test_openers.get(parsed.netloc)
        if opener is None:
            opener = build_opener(HTTPCookieProcessor(CookieJar()))
            login = Request(
                f"{parsed.scheme}://{parsed.netloc}/api/auth/login",
                data=json.dumps({"username": "admin", "password": "local-test-password"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with opener.open(login, timeout=5) as response:
                assert response.status == 200
            _test_openers[parsed.netloc] = opener
    else:
        opener = None
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(base, data=data, headers={"Content-Type": "application/json"}, method=method)
    with (opener.open(request, timeout=5) if opener else urlopen(request, timeout=5)) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read()


def _start(app):
    server = app.create_server(host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def _stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def _wait_for_status(base, run_id, expected):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _, _, body = _request(f"{base}/api/runs/{run_id}")
        run = json.loads(body)
        if run["run"]["status"] == expected:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach status {expected}")


class ToolThenAnswerProvider:
    model = "main-model"

    def __init__(self, instances):
        self.calls = 0
        self.instances = instances
        instances.append(self)

    def stream(self, _messages, _tools):
        self.calls += 1
        if self.calls == 1:
            return iter([
                StreamEvent(kind="tool_call", tool_call={
                    "id": "web-call-1", "name": "write_file",
                    "arguments": {"path": "web.txt", "content": "created from web"},
                }),
                StreamEvent(kind="usage", usage={"input_tokens": 20, "output_tokens": 4}),
                StreamEvent(kind="finish", finish_reason="tool_calls"),
            ])
        return iter([
            StreamEvent(kind="text", text="The file was created."),
            StreamEvent(kind="usage", usage={"input_tokens": 30, "output_tokens": 8}),
            StreamEvent(kind="finish", finish_reason="stop"),
        ])


class SlowProvider:
    model = "main-model"

    def stream(self, *_args):
        for index in range(200):
            time.sleep(0.01)
            yield StreamEvent(kind="text", text=f"chunk-{index} ")
        yield StreamEvent(kind="finish", finish_reason="stop")


def test_web_uses_js_session_login_and_protects_the_api(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    opener = build_opener(HTTPCookieProcessor())

    def request(path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(
            base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as response:
            return response.code, response.headers, response.read()

    try:
        status, _, page = request("/")
        assert status == 200 and b"login-form" in page
        assert request("/api/sessions")[0] == 401
        assert request("/api/auth/login", "POST", {
            "username": "admin", "password": "wrong-password",
        })[0] == 401

        status, headers, body = request("/api/auth/login", "POST", {
            "username": "admin", "password": "local-test-password",
        })
        assert status == 200 and json.loads(body)["authenticated"] is True
        cookie = headers.get("Set-Cookie", "")
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
        assert request("/api/auth/session")[0] == 200
        assert request("/api/sessions")[0] == 200
        assert request("/api/auth/logout", "POST", {})[0] == 200
        assert request("/api/auth/session")[0] == 401
    finally:
        _stop(server, thread)


def test_web_sandbox_starts_inspects_and_replays_saved_run(tmp_path):
    providers = []
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: ToolThenAnswerProvider(providers))
    server, thread, base = _start(app)
    try:
        status, content_type, page = _request(base)
        assert status == 200 and "text/html" in content_type
        assert b"Dagi Sandbox" in page

        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "web test"})
        session_id = json.loads(created)["session_id"]
        _, _, started = _request(
            f"{base}/api/sessions/{session_id}/runs", "POST", {"message": "create a file"}
        )
        run_id = json.loads(started)["run_id"]
        detail = _wait_for_status(base, run_id, "completed")

        assert detail["run"]["session_id"] == session_id
        assert detail["usage"]["provider_calls"] == 2
        assert len(detail["requests"]) == 2
        assert detail["tool_calls"][0]["tool_call_id"] == "web-call-1"
        assert (tmp_path / "workspace" / "web.txt").read_text() == "created from web"
        call_count = providers[0].calls

        _, content_type, stream = _request(f"{base}/api/runs/{run_id}/events?after=0")
        assert "text/event-stream" in content_type
        frames = [json.loads(line[6:]) for line in stream.decode().splitlines() if line.startswith("data: ")]
        assert any(event["kind"] == "tool_result" for event in frames)
        assert any(event["kind"] == "done" and event["status"] == "completed" for event in frames)
        assert all(event["session_id"] == session_id and event["run_id"] == run_id for event in frames)
        last_event_id = max(int(line[4:]) for line in stream.decode().splitlines() if line.startswith("id: "))
        _, _, replay = _request(f"{base}/api/runs/{run_id}/events?after={last_event_id}")
        assert replay == b""

        # Each concurrent handler gets its own SQLite connection.
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: _request(f"{base}/api/sessions"), range(12)))
        assert all(result[0] == 200 for result in results)
        _request(f"{base}/api/runs/{run_id}")
        assert providers[0].calls == call_count
    finally:
        _stop(server, thread)


def test_web_run_inspector_exposes_provider_error_and_unavailable_usage(tmp_path):
    class FailingProvider:
        model = "main-model"

        def stream(self, *_args):
            raise RuntimeError("simulated provider failure")

    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: FailingProvider())
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "error test"})
        session_id = json.loads(created)["session_id"]
        _, _, started = _request(
            f"{base}/api/sessions/{session_id}/runs", "POST", {"message": "fail"}
        )
        run_id = json.loads(started)["run_id"]
        detail = _wait_for_status(base, run_id, "error")

        assert "simulated provider failure" in detail["run"]["error"]
        assert detail["usage"]["provider_calls"] == 1
        assert detail["usage"]["source"] == "unavailable"
        _, _, stream = _request(f"{base}/api/runs/{run_id}/events?after=0")
        frames = [json.loads(line[6:]) for line in stream.decode().splitlines() if line.startswith("data: ")]
        assert any(event["kind"] == "error" for event in frames)
    finally:
        _stop(server, thread)


def test_web_inspector_exposes_parent_child_runs_and_child_model(tmp_path):
    from copy import deepcopy

    class DelegatingProvider:
        def __init__(self, model):
            self.model = model
            self.requests = []

        def stream(self, messages, _tools):
            self.requests.append(deepcopy(messages))
            if self.model == "main-model" and len(self.requests) == 1:
                return iter([
                    StreamEvent(kind="tool_call", tool_call={
                        "id": "delegate-web-1", "name": "delegate_task",
                        "arguments": {"task": "Find a concise answer", "model": "child-model", "context": "approved fact"},
                    }),
                    StreamEvent(kind="finish", finish_reason="tool_calls"),
                ])
            if self.model == "child-model":
                return iter([
                    StreamEvent(kind="text", text="Child answer."),
                    StreamEvent(kind="finish", finish_reason="stop"),
                ])
            return iter([
                StreamEvent(kind="text", text="Parent verified the child answer."),
                StreamEvent(kind="finish", finish_reason="stop"),
            ])

    providers = []
    def factory(model, *_args):
        provider = DelegatingProvider(model)
        providers.append(provider)
        return provider

    app = WebApp(_config(tmp_path), provider_factory=factory)
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "parent session"})
        parent_session = json.loads(created)["session_id"]
        _, _, started = _request(
            f"{base}/api/sessions/{parent_session}/runs", "POST", {"message": "delegate"}
        )
        parent_run_id = json.loads(started)["run_id"]
        parent = _wait_for_status(base, parent_run_id, "completed")

        assert len(parent["children"]) == 1
        assert parent["budget_usage"]["provider_calls"] == 3
        child = parent["children"][0]
        assert child["parent_run_id"] == parent_run_id
        assert child["depth"] == 1
        child_detail = _wait_for_status(base, child["run_id"], "completed")
        assert child_detail["run"]["parent_run_id"] == parent_run_id
        assert child_detail["parent"]["run_id"] == parent_run_id
        assert child_detail["provider_calls"][0]["model"] == "child-model"
        main = next(provider for provider in providers if provider.model == "main-model")
        assert "Child answer." in str(main.requests[1])
        _, _, page = _request(base)
        assert b"Parent and child runs" in page
    finally:
        _stop(server, thread)


def test_web_stop_cascades_to_an_active_child_agent(tmp_path):
    class MainProvider:
        model = "main-model"

        def __init__(self):
            self.calls = 0

        def stream(self, *_args):
            self.calls += 1
            if self.calls == 1:
                return iter([
                    StreamEvent(kind="tool_call", tool_call={
                        "id": "delegate-cancel", "name": "delegate_task",
                        "arguments": {"task": "wait for cancellation", "model": "child-model"},
                    }),
                    StreamEvent(kind="finish", finish_reason="tool_calls"),
                ])
            return iter([StreamEvent(kind="finish", finish_reason="stop")])

    child_started = Event()

    class ChildProvider:
        model = "child-model"

        def __init__(self):
            self.cancelled = Event()

        def stream(self, *_args):
            child_started.set()
            self.cancelled.wait(timeout=5)
            if self.cancelled.is_set():
                raise RuntimeError("child stream closed")
            yield StreamEvent(kind="finish", finish_reason="stop")

        def cancel(self):
            self.cancelled.set()

    main_provider = MainProvider()
    child_provider = ChildProvider()

    def factory(model, *_args):
        if model == "main-model": return main_provider
        if model == "child-model": return child_provider
        return SlowProvider()

    app = WebApp(_config(tmp_path), provider_factory=factory)
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "cancel child"})
        session_id = json.loads(created)["session_id"]
        _, _, started = _request(
            f"{base}/api/sessions/{session_id}/runs", "POST", {"message": "delegate"}
        )
        run_id = json.loads(started)["run_id"]
        assert child_started.wait(timeout=3)
        _, _, stopped = _request(f"{base}/api/runs/{run_id}/cancel", "POST", {})
        assert json.loads(stopped)["status"] == "cancelling"
        parent = _wait_for_status(base, run_id, "cancelled")
        assert child_provider.cancelled.is_set()
        assert len(parent["children"]) == 1
        child_run = parent["children"][0]["run_id"]
        assert _wait_for_status(base, child_run, "cancelled")["run"]["status"] == "cancelled"
    finally:
        _stop(server, thread)


def test_web_stop_cancels_run_and_persists_terminal_event(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "cancel test"})
        session_id = json.loads(created)["session_id"]
        _, _, started = _request(
            f"{base}/api/sessions/{session_id}/runs", "POST", {"message": "stream slowly"}
        )
        run_id = json.loads(started)["run_id"]
        time.sleep(0.08)
        _, _, stopped = _request(f"{base}/api/runs/{run_id}/cancel", "POST", {})
        assert json.loads(stopped)["status"] == "cancelling"
        detail = _wait_for_status(base, run_id, "cancelled")
        assert detail["run"]["status"] == "cancelled"
        _, _, stream = _request(f"{base}/api/runs/{run_id}/events?after=0")
        frames = [json.loads(line[6:]) for line in stream.decode().splitlines() if line.startswith("data: ")]
        assert any(event["kind"] == "done" and event["status"] == "cancelled" for event in frames)
    finally:
        _stop(server, thread)


def test_session_detail_snapshot_includes_message_ids_tool_state_and_event_cursor(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "snapshot test"})
        session_id = json.loads(created)["session_id"]
        state = StateStore(app.config.database)
        run_id = state.create_run(session_id)
        message_id = state.append_message(session_id, {"role": "user", "content": "read a file"})
        state.save_tool_round(
            session_id,
            run_id,
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "snapshot-call", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"src/main.py"}'},
            }]},
            [{"id": "snapshot-call", "name": "read_file", "arguments": {"path": "src/main.py"}}],
        )
        state.mark_tool_call_running("snapshot-call")
        event_id = state.append_run_event(session_id, run_id, {
            "kind": "tool_call", "session_id": session_id, "run_id": run_id,
            "tool_call_id": "snapshot-call", "tool_name": "read_file",
            "tool_args": {"path": "src/main.py"},
        })
        state.close()

        _, _, body = _request(f"{base}/api/sessions/{session_id}")
        snapshot = json.loads(body)
        assert snapshot["event_cursors"][run_id] == event_id
        assert any(message["id"] == message_id for message in snapshot["messages"])
        call = next(call for call in snapshot["tool_calls"] if call["tool_call_id"] == "snapshot-call")
        assert call["run_id"] == run_id
        assert call["status"] == "running"
    finally:
        _stop(server, thread)


def test_snapshot_to_sse_gap_replays_only_events_after_snapshot_cursor(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "snapshot gap"})
        session_id = json.loads(created)["session_id"]
        state = StateStore(app.config.database)
        run_id = state.create_run(session_id)
        first_id = state.append_run_event(session_id, run_id, {
            "kind": "text", "session_id": session_id, "run_id": run_id, "text": "snapshot event",
        })
        snapshot = state.session_snapshot(session_id)
        assert snapshot is not None
        cursor = snapshot["event_cursors"][run_id]
        assert cursor == first_id
        second_id = state.append_run_event(session_id, run_id, {
            "kind": "text", "session_id": session_id, "run_id": run_id, "text": "gap event",
        })
        state.finish_run(run_id, "completed")
        state.close()

        _, _, page_body = _request(
            f"{base}/api/runs/{run_id}/events?format=json&after=0&through={cursor}&limit=10"
        )
        page = json.loads(page_body)
        assert [row["id"] for row in page["events"]] == [first_id]
        _, _, stream = _request(f"{base}/api/runs/{run_id}/events?after={cursor}")
        frames = [json.loads(line[6:]) for line in stream.decode().splitlines() if line.startswith("data: ")]
        assert [event["text"] for event in frames] == ["gap event"]
        assert second_id > cursor
    finally:
        _stop(server, thread)


def test_running_snapshot_cursor_does_not_skip_uncommitted_terminal_event(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session_id = state.create_session("terminal race")
    run_id = state.create_run(session_id)
    before_terminal = state.append_run_event(session_id, run_id, {
        "kind": "text", "session_id": session_id, "run_id": run_id, "text": "work",
    })
    uncommitted_terminal = state.append_run_event(session_id, run_id, {
        "kind": "done", "session_id": session_id, "run_id": run_id, "status": "completed",
    })
    snapshot = state.session_snapshot(session_id)
    assert snapshot is not None
    assert snapshot["event_cursors"][run_id] == before_terminal
    assert snapshot["event_cursors"][run_id] < uncommitted_terminal
    state.close()


def test_run_event_json_pages_stop_at_snapshot_cursor(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "event page test"})
        session_id = json.loads(created)["session_id"]
        state = StateStore(app.config.database)
        run_id = state.create_run(session_id)
        first_id = state.append_run_event(session_id, run_id, {"kind": "text", "session_id": session_id, "run_id": run_id, "text": "first"})
        cursor = state.append_run_event(session_id, run_id, {"kind": "text", "session_id": session_id, "run_id": run_id, "text": "second"})
        state.append_run_event(session_id, run_id, {"kind": "text", "session_id": session_id, "run_id": run_id, "text": "after snapshot"})
        state.finish_run(run_id, "completed")
        state.close()

        _, content_type, body = _request(
            f"{base}/api/runs/{run_id}/events?format=json&after=0&through={cursor}&limit=1"
        )
        assert "application/json" in content_type
        first = json.loads(body)
        assert [row["id"] for row in first["events"]] == [first_id]
        assert first["has_more"] is True
        _, _, body = _request(
            f"{base}/api/runs/{run_id}/events?format=json&after={first['next_after']}&through={cursor}&limit=1"
        )
        second = json.loads(body)
        assert [row["event"]["text"] for row in second["events"]] == ["second"]
        assert second["has_more"] is False
    finally:
        _stop(server, thread)


def test_web_run_uses_the_session_workspace(tmp_path):
    providers = []
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: ToolThenAnswerProvider(providers))
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "child workspace"})
        session_id = json.loads(created)["session_id"]
        state = StateStore(app.config.database)
        state.set_session_workspace(session_id, ".dagi-children/web-child")
        state.close()

        _, _, started = _request(
            f"{base}/api/sessions/{session_id}/runs", "POST", {"message": "create a child file"}
        )
        run_id = json.loads(started)["run_id"]
        _wait_for_status(base, run_id, "completed")

        child_workspace = tmp_path / "workspace" / ".dagi-children" / "web-child"
        assert (child_workspace / "web.txt").read_text(encoding="utf-8") == "created from web"
        assert not (tmp_path / "workspace" / "web.txt").exists()
    finally:
        _stop(server, thread)
