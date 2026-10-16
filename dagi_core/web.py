"""Loopback-only visual sandbox backed by the existing SQLite agent state."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from threading import Event, Lock, Thread
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .agent import Agent
from .config import Config, load_config
from .context import ContextBuilder
from .provider import OpenAICompatibleProvider
from .state import StateStore
from .tools import ToolRegistry

ProviderFactory = Callable[[str, str, str], Any]


@dataclass
class _RunControl:
    session_id: int
    cancellation: Event = field(default_factory=Event)
    thread: Thread | None = None
    providers: list[Any] = field(default_factory=list)


class WebApp:
    """A threaded HTTP shell; each request/worker opens its own SQLite connection."""

    def __init__(self, config: Config, provider_factory: ProviderFactory | None = None):
        self.config = config
        self.provider_factory = provider_factory or OpenAICompatibleProvider
        self._runs: dict[str, _RunControl] = {}
        self._lock = Lock()

    def create_server(self, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def _send_json(self, status: int, payload: Any) -> None:
                data = json.dumps(_json_safe(payload), ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 64_000:
                    raise ValueError("request body must be at most 64 KB")
                data = self.rfile.read(length)
                value = json.loads(data or b"{}")
                if not isinstance(value, dict):
                    raise ValueError("request body must be a JSON object")
                return value

            def _state(self) -> StateStore:
                # This handler runs in a dedicated HTTP thread; never share connections.
                return StateStore(app.config.database)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                path = parsed.path
                try:
                    if path == "/" or path == "/app.js":
                        self._static(path)
                    elif path == "/api/sessions":
                        with _StateContext(self._state()) as state:
                            sessions = state.list_sessions(100)
                            for session in sessions:
                                session["runs"] = state.list_runs(session["id"], 20)
                            self._send_json(200, {"sessions": sessions})
                    elif match := re.fullmatch(r"/api/sessions/(\d+)", path):
                        session_id = int(match.group(1))
                        with _StateContext(self._state()) as state:
                            session = state.get_session(session_id)
                            if session is None:
                                self._send_json(404, {"error": "session not found"})
                                return
                            self._send_json(200, {
                                "session": session,
                                "runs": state.list_runs(session_id, 100),
                                "messages": state.message_records(session_id),
                            })
                    elif match := re.fullmatch(r"/api/runs/([^/]+)/events", path):
                        self._stream_events(match.group(1), parsed.query)
                    elif match := re.fullmatch(r"/api/runs/([^/]+)", path):
                        self._run_detail(match.group(1))
                    else:
                        self._send_json(404, {"error": "not found"})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._send_json(400, {"error": str(exc)})
                except Exception:
                    self._send_json(500, {"error": "sandbox request failed"})

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                try:
                    body = self._read_json()
                    if parsed.path == "/api/sessions":
                        title = body.get("title")
                        if title is not None and not isinstance(title, str):
                            raise ValueError("title must be text")
                        with _StateContext(self._state()) as state:
                            session_id = state.create_session(title)
                        self._send_json(201, {"session_id": session_id})
                    elif match := re.fullmatch(r"/api/sessions/(\d+)/runs", parsed.path):
                        self._start_run(int(match.group(1)), body)
                    elif match := re.fullmatch(r"/api/runs/([^/]+)/cancel", parsed.path):
                        self._cancel_run(match.group(1))
                    else:
                        self._send_json(404, {"error": "not found"})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._send_json(400, {"error": str(exc)})
                except Exception:
                    self._send_json(500, {"error": "sandbox request failed"})

            def _static(self, path: str) -> None:
                name = "index.html" if path == "/" else "app.js"
                content_type = "text/html; charset=utf-8" if name.endswith(".html") else "text/javascript; charset=utf-8"
                data = files("dagi_core").joinpath("static", name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _run_detail(self, run_id: str) -> None:
                with _StateContext(self._state()) as state:
                    run = state.get_run(run_id)
                    if run is None:
                        self._send_json(404, {"error": "run not found"})
                        return
                    provider_calls = state.list_provider_calls(run_id)
                    requests = []
                    for call in provider_calls:
                        requests.append({
                            "provider_call_id": call["id"],
                            "purpose": call["purpose"],
                            "model": call["model"],
                            "request": state.get_provider_request(call["id"]),
                        })
                    tool_calls = [
                        call for call in state.list_tool_calls(run["session_id"])
                        if call["run_id"] == run_id
                    ]
                    self._send_json(200, {
                        "run": run,
                        "usage": state.usage_summary(run_id),
                        "provider_calls": provider_calls,
                        "requests": requests,
                        "tool_calls": tool_calls,
                        "messages": state.message_records(run["session_id"]),
                        "event_count": len(state.list_run_events(run_id, limit=5000)),
                    })

            def _stream_events(self, run_id: str, query: str) -> None:
                params = parse_qs(query)
                after = int(params.get("after", ["0"])[0])
                last_header = self.headers.get("Last-Event-ID")
                if last_header:
                    after = max(after, int(last_header))
                state = self._state()
                try:
                    run = state.get_run(run_id)
                    if run is None:
                        self._send_json(404, {"error": "run not found"})
                        return
                    self.close_connection = True
                    self.send_response(200)
                    self.send_header("Connection", "close")
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache, no-transform")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    while True:
                        rows = state.list_run_events(run_id, after_id=after)
                        for row in rows:
                            frame = f"id: {row['id']}\ndata: {json.dumps(row['event'], ensure_ascii=False)}\n\n"
                            self.wfile.write(frame.encode("utf-8"))
                            self.wfile.flush()
                            after = row["id"]
                        run = state.get_run(run_id)
                        if run is None or run["status"] != "running":
                            break
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError):
                    return
                finally:
                    state.close()

            def _start_run(self, session_id: int, body: dict[str, Any]) -> None:
                message = body.get("message")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("message must be non-empty text")
                with _StateContext(self._state()) as state:
                    if state.get_session(session_id) is None:
                        self._send_json(404, {"error": "session not found"})
                        return
                    run_id = state.create_run(session_id)
                control = _RunControl(session_id)
                with app._lock:
                    if any(item.session_id == session_id for item in app._runs.values()):
                        with _StateContext(self._state()) as state:
                            state.finish_run(run_id, "error", "another run is already active in this session")
                        self._send_json(409, {"error": "a run is already active for this session"})
                        return
                    app._runs[run_id] = control
                    control.thread = Thread(
                        target=app._execute_run,
                        args=(run_id, session_id, message, control),
                        daemon=True,
                    )
                    control.thread.start()
                self._send_json(202, {"run_id": run_id, "session_id": session_id, "status": "running"})

            def _cancel_run(self, run_id: str) -> None:
                with app._lock:
                    control = app._runs.get(run_id)
                if control is None:
                    self._send_json(409, {"error": "run is not active"})
                    return
                control.cancellation.set()
                for provider in tuple(control.providers):
                    cancel = getattr(provider, "cancel", None)
                    if callable(cancel):
                        try:
                            cancel()
                        except Exception:
                            pass
                self._send_json(202, {"run_id": run_id, "status": "cancelling"})

        server = ThreadingHTTPServer((host, port), Handler)
        server.daemon_threads = True
        return server

    def _execute_run(self, run_id: str, session_id: int, message: str, control: _RunControl) -> None:
        state = StateStore(self.config.database)
        try:
            provider = self.provider_factory(self.config.model, self.config.api_key, self.config.base_url)
            compression_provider = self.provider_factory(
                self.config.compression_model, self.config.api_key, self.config.base_url
            )
            with self._lock:
                control.providers = [provider, compression_provider]
                already_cancelled = control.cancellation.is_set()
            if already_cancelled:
                for active_provider in control.providers:
                    cancel = getattr(active_provider, "cancel", None)
                    if callable(cancel):
                        cancel()
            tools = ToolRegistry(self.config.workspace, state, session_id, shell_enabled=False)
            context = ContextBuilder(
                state,
                max_tokens=self.config.context_limit_tokens,
                max_tool_result_chars=self.config.context_max_tool_result_chars,
                compression_provider=compression_provider,
                usage_policy=self.config.usage_policy,
            )
            agent = Agent(
                provider, tools, state, session_id,
                usage_policy=self.config.usage_policy, context_builder=context,
            )
            for _event in agent.run_turn(message, run_id=run_id, cancel_event=control.cancellation):
                pass
        except Exception as exc:
            run = state.get_run(run_id)
            if run is not None and run["status"] == "running":
                error_text = f"web worker error: {type(exc).__name__}: {exc}"
                for kind, text, status in (
                    ("error", error_text, None),
                    ("done", None, "error"),
                ):
                    event = {"kind": kind, "session_id": session_id, "run_id": run_id, "text": text, "status": status}
                    state.append_run_event(session_id, run_id, event)
                state.finish_run(run_id, "error", error_text)
        finally:
            state.close()
            with self._lock:
                self._runs.pop(run_id, None)

    def serve(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        server = self.create_server(host, port)
        print(f"Dagi sandbox listening on http://{host}:{server.server_address[1]}")
        try:
            server.serve_forever()
        finally:
            server.server_close()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class _StateContext:
    def __init__(self, state: StateStore):
        self.state = state

    def __enter__(self) -> StateStore:
        return self.state

    def __exit__(self, *_args: Any) -> None:
        self.state.close()


def main() -> None:
    config = load_config()
    host = os.environ.get("DAGI_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("DAGI_WEB_PORT", "8765"))
    WebApp(config).serve(host, port)


if __name__ == "__main__":
    main()
