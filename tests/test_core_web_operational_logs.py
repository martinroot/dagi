"""Regression tests for redacted operational logs in the visual sandbox."""

import json
import logging
from http.cookiejar import CookieJar
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener

from dagi_core.auth import hash_password
from dagi_core.config import Config
from dagi_core.usage import UsagePolicy
from dagi_core.web import WebApp
from dagi_core.worker import WorkerClient


LOGGER_NAME = "dagi.sandbox"


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
        web_password_hash=hash_password(
            "local-test-password", salt=b"0123456789abcdef", iterations=1_000
        ),
        web_cookie_path="/",
        web_public_origin="",
        web_cookie_secure=False,
    )


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


def _opener(base):
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    login = Request(
        f"{base}/api/auth/login",
        data=json.dumps({"username": "admin", "password": "local-test-password"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(login, timeout=5) as response:
        assert response.status == 200
    return opener


def _call(opener, base, path, method="GET", payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = Request(
        f"{base}{path}", data=data, headers=request_headers, method=method
    )
    try:
        with opener.open(request, timeout=5) as response:
            return response.status
    except HTTPError as exc:
        return exc.code


def _entries(caplog):
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == LOGGER_NAME
    ]


class _BrokenWorker(WorkerClient):
    def __init__(self):
        pass

    def request(self, *_args, **_kwargs):
        raise RuntimeError(
            "Authorization: Bearer sk-abcdefghijklmnop "
            "password=hunter2 api_key=ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        )


def test_successful_request_emits_no_operational_log(tmp_path, caplog):
    server, thread, base = _start(WebApp(_config(tmp_path)))
    try:
        opener = _opener(base)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            status = _call(opener, base, "/api/health")
        assert status == 200
        assert _entries(caplog) == []
    finally:
        _stop(server, thread)


def test_failure_log_is_json_with_route_template_and_per_request_id(tmp_path, caplog):
    server, thread, base = _start(WebApp(_config(tmp_path)))
    try:
        opener = _opener(base)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            first = _call(opener, base, f"/api/templates/{quote('secret-template-name')}")
            second = _call(opener, base, "/api/templates/another-name")
        assert first == second == 404

        entries = _entries(caplog)
        assert len(entries) == 2
        for entry in entries:
            assert entry["event"] == "sandbox.http.failure"
            assert entry["method"] == "GET"
            assert entry["route"] == "/api/templates/:name"
            assert entry["status"] == 404
            assert entry["error"] == "template not found"
            assert isinstance(entry["request_id"], str) and entry["request_id"]
        assert entries[0]["request_id"] != entries[1]["request_id"]
        rendered = "\n".join(record.message for record in caplog.records)
        assert "secret-template-name" not in rendered
        assert "another-name" not in rendered
    finally:
        _stop(server, thread)


def test_failure_log_never_includes_headers_or_bodies(tmp_path, caplog):
    server, thread, base = _start(WebApp(_config(tmp_path)))
    try:
        opener = _opener(base)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            status = _call(
                opener,
                base,
                "/api/templates",
                method="POST",
                payload={"name": "", "password": "body-secret-xyz"},
                headers={"Authorization": "Bearer header-token-xyz"},
            )
        assert status == 400
        entries = _entries(caplog)
        assert len(entries) == 1
        assert set(entries[0]) <= {
            "event", "request_id", "method", "route", "status", "error", "error_type"
        }
        assert entries[0]["route"] == "/api/templates"
        rendered = "\n".join(record.message for record in caplog.records)
        assert "body-secret-xyz" not in rendered
        assert "header-token-xyz" not in rendered
    finally:
        _stop(server, thread)


def test_proxy_failure_log_redacts_worker_error(tmp_path, caplog):
    app = WebApp(_config(tmp_path))
    app.workers["broken"] = _BrokenWorker()
    server, thread, base = _start(app)
    try:
        opener = _opener(base)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            status = _call(opener, base, "/api/workers/broken/proxy/api/health")
        assert status == 502
        entries = _entries(caplog)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["status"] == 502
        assert entry["route"] == "/api/workers/:worker/proxy/:path"
        assert entry["error_type"] == "RuntimeError"
        assert "[REDACTED]" in entry["error"]
        rendered = "\n".join(record.message for record in caplog.records)
        for secret in ("sk-abcdefghijklmnop", "hunter2", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"):
            assert secret not in rendered
    finally:
        _stop(server, thread)


def test_unhandled_server_error_is_logged_once(tmp_path, caplog, monkeypatch):
    app = WebApp(_config(tmp_path))

    def _explode(*_args, **_kwargs):
        raise RuntimeError("unexpected backend failure")

    monkeypatch.setattr(app, "list_artifacts", _explode)
    server, thread, base = _start(app)
    try:
        opener = _opener(base)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            status = _call(opener, base, "/api/sessions/7/artifacts")
        assert status == 500
        entries = _entries(caplog)
        assert len(entries) == 1
        assert entries[0]["status"] == 500
        assert entries[0]["route"] == "/api/sessions/:id/artifacts"
        assert entries[0]["error_type"] == "RuntimeError"
        assert entries[0]["error"] == "unexpected backend failure"
    finally:
        _stop(server, thread)
