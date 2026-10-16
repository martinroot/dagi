from concurrent.futures import ThreadPoolExecutor
import json
import time
from threading import Thread
from urllib.request import Request, urlopen

from dagi_core.config import Config
from dagi_core.provider import StreamEvent
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
    )


def _request(base, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(base, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urlopen(request, timeout=5) as response:
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
