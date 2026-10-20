from concurrent.futures import ThreadPoolExecutor
import json
import time
from dataclasses import replace
from copy import deepcopy
from threading import Event, Thread
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from dagi_core.auth import hash_password
from dagi_core.config import Config
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore, goal_lesson_fingerprint
from dagi_core.usage import UsagePolicy
from dagi_core.web import WebApp, _runtime_inspector_status


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


def _wait_for_status(base, run_id, expected, timeout=5):
    deadline = time.monotonic() + timeout
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
        self.requests = []
        instances.append(self)

    def stream(self, messages, _tools):
        self.requests.append(deepcopy(messages))
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
        session_workspace = json.loads(created)["workspace"]
        _, _, empty_snapshot = _request(f"{base}/api/sessions/{session_id}")
        empty_runtime = json.loads(empty_snapshot)["runtime_status"]
        assert empty_runtime["role"] is None and empty_runtime["latest_reflection"] is None
        _, _, started = _request(
            f"{base}/api/sessions/{session_id}/runs", "POST", {"message": "create a file"}
        )
        run_id = json.loads(started)["run_id"]
        detail = _wait_for_status(base, run_id, "completed")

        assert detail["run"]["session_id"] == session_id
        assert detail["usage"]["provider_calls"] == 2
        assert len(detail["requests"]) == 2
        assert detail["tool_calls"][0]["tool_call_id"] == "web-call-1"
        assert (tmp_path / "workspace" / session_workspace / "web.txt").read_text() == "created from web"
        runtime = detail["runtime_status"]
        assert runtime["role"] == "root"
        assert runtime["phase"] == "provider_request"
        assert runtime["latest_reflection"]["trigger"] == "run_concluded"
        assert runtime["tool_outcome"] == {"tool_name": "write_file", "status": "succeeded"}
        assert runtime["goal_status"] is None
        assert runtime["next_action"] is None
        assert "provider-turn completion" in runtime["recovery_guidance"]
        assert "web-call-1" in runtime["last_evidence"]
        assert "api_key" not in runtime and "environment" not in runtime
        assert "placeholder-for-test" not in json.dumps(runtime)
        call_count = providers[0].calls
        persisted_before = StateStore(app.config.database)
        reflections_before = persisted_before.list_tool_reflections(session_id, limit=3)
        goals_before = persisted_before.list_goals(session_id)
        persisted_before.close()
        _, _, session_snapshot = _request(f"{base}/api/sessions/{session_id}")
        assert json.loads(session_snapshot)["runtime_status"]["latest_reflection"]["trigger"] == "run_concluded"
        _, _, unrelated_created = _request(f"{base}/api/sessions", "POST", {"title": "unrelated"})
        unrelated_id = json.loads(unrelated_created)["session_id"]
        _, _, unrelated_snapshot = _request(f"{base}/api/sessions/{unrelated_id}")
        unrelated_runtime = json.loads(unrelated_snapshot)["runtime_status"]
        assert unrelated_runtime["latest_reflection"] is None
        assert unrelated_runtime["tool_outcome"] is None

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
        persisted_after = StateStore(app.config.database)
        assert persisted_after.list_tool_reflections(session_id, limit=3) == reflections_before
        assert persisted_after.list_goals(session_id) == goals_before
        persisted_after.close()
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


def test_run_inspector_explains_unavailable_cost_and_names_the_unpriced_model(tmp_path):
    class UnpricedProvider:
        model = "main-model"

        def stream(self, *_args):
            yield StreamEvent(kind="text", text="hello")
            yield StreamEvent(kind="finish", finish_reason="stop")

    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: UnpricedProvider())
    server, thread, base = _start(app)
    try:
        _, _, created = _request(f"{base}/api/sessions", "POST", {"title": "cost test"})
        session_id = json.loads(created)["session_id"]
        _, _, started = _request(
            f"{base}/api/sessions/{session_id}/runs", "POST", {"message": "hello"}
        )
        run_id = json.loads(started)["run_id"]
        detail = _wait_for_status(base, run_id, "completed")

        assert detail["cost_status"]["status"] in {"unavailable", "partial"}
        assert detail["cost_status"]["unpriced_models"] == ["main-model"]
        assert "DAGI_MODEL_PRICES" in detail["cost_status"]["explanation"]
        assert detail["cost_status"]["cost_usd"] is None
        assert detail["budget_cost_status"]["unpriced_models"] == ["main-model"]
    finally:
        _stop(server, thread)


def test_a_shell_command_from_a_chat_session_waits_for_operator_approval(tmp_path):
    from dagi_core.config import Config
    from dagi_core.auth import hash_password

    config = replace(_config(tmp_path), web_enable_shell=True, web_command_approval_timeout=5)
    app = WebApp(config, provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    opener = build_opener(HTTPCookieProcessor())

    def request(path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(
            base + path, data=data,
            headers={"Content-Type": "application/json"}, method=method,
        )
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, json.loads(response.read() or b"{}")
        except HTTPError as response:
            return response.code, json.loads(response.read() or b"{}")

    try:
        request("/api/auth/login", "POST", {"username": "admin", "password": "local-test-password"})
        assert request("/api/approvals")[1]["approvals"] == []

        registry = app.approvals
        decision = {}

        def ask():
            decision["approved"] = registry.request("uname -a", session_id=1, run_id="r1")

        import threading
        worker = threading.Thread(target=ask)
        worker.start()
        deadline = time.monotonic() + 3
        pending = []
        while time.monotonic() < deadline:
            pending = registry.pending()
            if pending:
                break
            time.sleep(0.01)
        assert pending, "the command must wait for the operator"
        status, body = request(f"/api/approvals/{pending[0]['id']}", "POST", {"approved": True})
        assert status == 200 and body["approved"] is True
        worker.join(timeout=5)
        assert decision["approved"] is True
        assert request("/api/approvals")[1]["approvals"] == []
    finally:
        _stop(server, thread)


def test_document_artifact_is_listed_and_downloaded_for_the_chat(tmp_path):
    from dataclasses import replace
    app = WebApp(replace(_config(tmp_path), enable_documents=True), provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    opener = build_opener(HTTPCookieProcessor())

    def request(path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(
            base + path, data=data,
            headers={"Content-Type": "application/json"}, method=method,
        )
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as response:
            return response.code, response.headers, response.read()

    try:
        request("/api/auth/login", "POST", {"username": "admin", "password": "local-test-password"})
        status, _, created = request("/api/sessions", "POST", {"title": "contract"})
        session_id = json.loads(created)["session_id"]
        workspace = app.config.workspace / f"sessions/{session_id}"
        workspace.mkdir(parents=True, exist_ok=True)
        # the session owns its own workspace under the configured root
        state = StateStore(app.config.database)
        try:
            state._db.execute("UPDATE sessions SET workspace=? WHERE id=?", (f"sessions/{session_id}", session_id))
            state._db.commit()
        finally:
            state.close()
        (workspace / "contract.docx").write_bytes(b"PK\x03\x04fake-docx-bytes")

        status, _, body = request(f"/api/sessions/{session_id}/artifacts")
        assert status == 200
        artifacts = json.loads(body)["artifacts"]
        assert any(item["name"] == "contract.docx" for item in artifacts)

        status, headers, data = request(f"/api/sessions/{session_id}/artifacts/contract.docx")
        assert status == 200
        assert data.startswith(b"PK")
        assert "attachment" in (headers.get("Content-Disposition") or "")

        assert request("/api/sessions/%d/artifacts/../secret" % session_id)[0] in (400, 404)
    finally:
        _stop(server, thread)


def test_session_deletion_api_removes_one_session_and_purges_the_rest(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    opener = build_opener(HTTPCookieProcessor())

    def request(path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(
            base + path, data=data,
            headers={"Content-Type": "application/json"}, method=method,
        )
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, json.loads(response.read() or b"{}")
        except HTTPError as response:
            return response.code, json.loads(response.read() or b"{}")

    try:
        request("/api/auth/login", "POST", {"username": "admin", "password": "local-test-password"})
        status, first = request("/api/sessions", "POST", {"title": "old one"})
        assert status == 201
        status, second = request("/api/sessions", "POST", {"title": "old two"})
        assert status == 201

        status, body = request(f"/api/sessions/{first['session_id']}", "DELETE")
        assert status == 200 and body["deleted"] is True
        assert request(f"/api/sessions/{first['session_id']}")[0] == 404

        assert request("/api/sessions/purge", "POST", {})[0] == 400, "a purge needs an explicit confirmation"
        status, body = request("/api/sessions/purge", "POST", {"confirm": "DELETE ALL"})
        assert status == 200 and body["remaining"] == []
        assert request("/api/sessions")[1]["sessions"] == []
    finally:
        _stop(server, thread)


def test_template_api_captures_a_session_and_clones_a_clean_session(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_args: SlowProvider())
    server, thread, base = _start(app)
    opener = build_opener(HTTPCookieProcessor())

    def request(path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(
            base + path, data=data,
            headers={"Content-Type": "application/json"}, method=method,
        )
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, json.loads(response.read() or b"{}")
        except HTTPError as response:
            return response.code, json.loads(response.read() or b"{}")

    try:
        request("/api/auth/login", "POST", {"username": "admin", "password": "local-test-password"})
        status, created = request("/api/sessions", "POST", {"title": "Hermes_ssh_tg"})
        assert status == 201
        session_id = created["session_id"]
        state = StateStore(app.config.database)
        try:
            state.append_message(session_id, {
                "role": "user",
                "content": "Install the Hermes agent on a remote server, create a user and a token, and set up Telegram.",
            })
        finally:
            state.close()

        status, body = request("/api/templates", "POST", {
            "name": "hermes-deploy", "source_session_id": session_id,
            "brief": "Remote host, dedicated user, protected token, bot online.",
        })
        assert status == 201
        template = body["template"]
        assert "Install the Hermes agent" in template["task"]
        assert template["brief"].startswith("Remote host")

        status, body = request("/api/templates")
        assert status == 200 and [item["name"] for item in body["templates"]] == ["hermes-deploy"]

        status, body = request(f"/api/templates/{template['id']}/clone", "POST", {})
        assert status == 201
        clone = body["clone"]
        assert clone["session_id"] != session_id
        assert clone["task"].startswith("Install the Hermes agent")

        status, body = request(f"/api/sessions/{clone['session_id']}")
        assert status == 200
        assert body["messages"] == [], "a clone must start with a clean transcript"
        assert body["runs"] == [], "a clone must start with no runs"

        assert request(f"/api/templates/{template['id']}", "DELETE")[0] == 200
        assert request("/api/templates")[1]["templates"] == []
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
                        "arguments": {
                            "task": "Find a concise answer", "model": "child-model", "context": "approved fact",
                            "purpose": "Supports the parent objective", "required_output": "One-sentence answer",
                            "acceptance_check_ids": ["parent-check-1"],
                        },
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
        runtime = child_detail["runtime_status"]
        assert runtime["role"] == "child"
        assert runtime["assignment"] == "Find a concise answer"
        assert runtime["purpose"] == "Supports the parent objective"
        assert runtime["required_output"] == "One-sentence answer"
        assert runtime["acceptance_check_ids"] == ["parent-check-1"]
        assert runtime["phase"] == "provider_request"
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
        detail = _wait_for_status(base, run_id, "completed")
        assert detail["runtime_status"]["workspace"] == ".dagi-children/web-child"

        child_workspace = tmp_path / "workspace" / ".dagi-children" / "web-child"
        system_content = providers[0].requests[0][0]["content"]
        start = system_content.index("DAGI_RUNTIME_CONTEXT_JSON_BEGIN\n") + len("DAGI_RUNTIME_CONTEXT_JSON_BEGIN\n")
        end = system_content.index("\nDAGI_RUNTIME_CONTEXT_JSON_END", start)
        runtime_context = json.loads(system_content[start:end])
        assert runtime_context["environment"]["entry_point"] == "web"
        assert runtime_context["environment"]["workspace"] == ".dagi-children/web-child"
        assert (child_workspace / "web.txt").read_text(encoding="utf-8") == "created from web"
        assert not (tmp_path / "workspace" / "web.txt").exists()
    finally:
        _stop(server, thread)


def test_runtime_inspector_is_bounded_and_scoped_to_the_session_goal(tmp_path):
    config = _config(tmp_path)
    state = StateStore(config.database)
    session_a = state.create_session("goal-a")
    session_b = state.create_session("goal-b")
    session_c = state.create_session("blocked-goal")
    empty_session = state.create_session("empty")
    run_a = state.create_run(session_a)
    run_b = state.create_run(session_b)
    run_c = state.create_run(session_c)

    checks_a = [{"type": "json_valid", "path": f"result-{index}.json"} for index in range(4)]
    goal_a = state.create_goal(session_a, "create valid JSON", checks_a, 2)
    state.link_goal_run(goal_a, run_a)

    def add_lesson(session_id, goal_id, check, label, index):
        action_fingerprint = f"{index + 1:064x}"
        state.record_goal_reflection(
            goal_id=goal_id,
            iteration=0,
            check_index=index,
            expected=check,
            observed={"passed": False, "detail": "invalid JSON"},
            evidence_ids=[f"goal-check:{label}{index}"],
            failure_fingerprint=f"{index + 20:064x}",
            action_fingerprint=action_fingerprint,
        )
        state.update_goal_reflection_followup(
            goal_id,
            index,
            True,
            next_change="Observed tools: write_file",
            evidence_ids=[f"run:{label}{index}", f"tool:{label}{index}"],
            next_action_fingerprint=action_fingerprint,
        )
        reflection = state.get_latest_goal_reflection(goal_id, index)
        return state.record_goal_lesson(
            session_id=session_id,
            goal_id=goal_id,
            reflection_id=reflection["id"],
            check_type=check["type"],
            check_key=check["path"],
            pattern_fingerprint=goal_lesson_fingerprint(check["type"], check["path"], action_fingerprint),
            lesson=f"Use the verified action for {check['path']}.",
            evidence_ids=reflection["evidence_ids"],
        )

    for index, check in enumerate(checks_a):
        add_lesson(session_a, goal_a, check, "a", index)

    check_b = {"type": "json_valid", "path": "result-0.json"}
    goal_b = state.create_goal(session_b, "create another JSON", [check_b], 2)
    state.link_goal_run(goal_b, run_b)
    lesson_b = add_lesson(session_b, goal_b, check_b, "b", 0)

    check_c = {"type": "file_exists", "path": "blocked.txt"}
    goal_c = state.create_goal(session_c, "create blocked file", [check_c], 3)
    state.link_goal_run(goal_c, run_c)
    for iteration in range(3):
        blocker_reflection = state.record_goal_reflection(
            goal_id=goal_c,
            iteration=iteration,
            check_index=0,
            expected=check_c,
            observed={"passed": False, "detail": "file is absent"},
            evidence_ids=[f"goal-check:c{iteration}"],
            failure_fingerprint="e" * 64,
            action_fingerprint="f" * 64,
        )
    state.update_goal(goal_a, "interrupted", feedback=[])
    state.update_goal(goal_b, "interrupted", feedback=[])
    state.update_goal(goal_c, "limit", feedback=[])

    blocker_status = _runtime_inspector_status(state, session_c, run_c)
    assert blocker_reflection["repeat_count"] == 2
    assert blocker_reflection["blocker"]
    assert blocker_status["blocker"] == "Repeated check/action failure threshold reached"
    assert blocker_status["goal_status"] == "limit"


    reflections_before = state.list_goal_reflections(goal_a)
    lessons_before = state.list_goal_lessons(
        session_a, check_type="json_valid", check_key="result-0.json", limit=3,
    )
    status_a = _runtime_inspector_status(state, session_a, run_a)
    status_b = _runtime_inspector_status(state, session_b, run_b)
    empty = _runtime_inspector_status(state, empty_session)
    cross_session = _runtime_inspector_status(state, session_b, run_a)
    assert state.list_goal_reflections(goal_a) == reflections_before
    assert state.list_goal_lessons(
        session_a, check_type="json_valid", check_key="result-0.json", limit=3,
    ) == lessons_before
    state.close()

    assert status_a["goal_status"] == "interrupted"
    assert status_a["check_result"] == {
        "observed_passed": False, "followup_passed": True, "detail": "invalid JSON",
    }
    assert status_a["latest_reflection"]["trigger"] == "acceptance_check_failed"
    assert status_a["blocker"] is None
    assert len(status_a["lessons"]) == 3
    assert all(item["status"] == "candidate" and item["check_type"] == "json_valid" for item in status_a["lessons"])
    assert all(item["evidence_ids"] and all(value.startswith(("goal-check:a", "run:a", "tool:a")) for value in item["evidence_ids"]) for item in status_a["lessons"])
    assert all(len(item["lesson"]) <= 512 and len(item["evidence_ids"]) <= 3 for item in status_a["lessons"])
    assert status_b["lessons"][0]["evidence_ids"] == lesson_b["evidence_ids"]
    assert empty["role"] is None and empty["goal_status"] is None and empty["lessons"] == []
    assert cross_session == {}

    app = WebApp(config, provider_factory=lambda *_args: None)
    server, thread, base = _start(app)
    try:
        _, _, detail_a = _request(f"{base}/api/runs/{run_a}")
        _, _, detail_b = _request(f"{base}/api/runs/{run_b}")
        _, _, detail_c = _request(f"{base}/api/runs/{run_c}")
        _, _, empty_snapshot = _request(f"{base}/api/sessions/{empty_session}")
        api_status_a = json.loads(detail_a)["runtime_status"]
        api_status_b = json.loads(detail_b)["runtime_status"]
        api_status_c = json.loads(detail_c)["runtime_status"]
        api_empty = json.loads(empty_snapshot)["runtime_status"]
        assert api_status_c["blocker"] == "Repeated check/action failure threshold reached"
        assert api_status_c["goal_status"] == "limit"
        assert api_status_a == status_a
        assert api_status_b["lessons"][0]["evidence_ids"] == lesson_b["evidence_ids"]
        assert all(not any(value.startswith("goal-check:b") for value in item["evidence_ids"]) for item in api_status_a["lessons"])
        assert api_empty["role"] is None and api_empty["latest_reflection"] is None
    finally:
        _stop(server, thread)
