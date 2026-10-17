import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest

from dagi_core.worker import WorkerClient, load_workers


@pytest.mark.parametrize("url", ["http://worker.example", "http://10.0.0.7:8765"])
def test_remote_worker_token_transport_requires_https(url):
    with pytest.raises(ValueError, match="HTTPS"):
        WorkerClient("remote", url, "not-a-real-token")


def test_worker_allows_http_only_for_loopback_tunnels():
    assert WorkerClient("v4", "http://127.0.0.1:8765", "test-token").url == "http://127.0.0.1:8765"
    assert WorkerClient("v6", "http://[::1]:8765", "test-token").url == "http://[::1]:8765"
    assert WorkerClient("localhost", "http://localhost:8765", "test-token").url == "http://localhost:8765"
    assert WorkerClient("tls", "https://worker.example", "test-token").url == "https://worker.example"


def test_worker_client_rejects_redirect_without_leaking_bearer_token():
    target_seen = Event()
    target = None

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            target_seen.set()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"healthy":true}')

        def log_message(self, format, *args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_thread = Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    redirect_location = f"http://127.0.0.1:{target.server_port}/api/health"

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", redirect_location)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    redirect_thread = Thread(target=redirect.serve_forever, daemon=True)
    redirect_thread.start()
    secret = "test-token-must-not-leak"
    client = WorkerClient("redirector", f"http://127.0.0.1:{redirect.server_port}", secret)
    try:
        with pytest.raises(ValueError, match="HTTP 302") as exc:
            client.request("/api/health")
        assert secret not in str(exc.value)
        assert not target_seen.wait(0.1)
        assert secret not in repr(client)
    finally:
        redirect.shutdown()
        redirect.server_close()
        target.shutdown()
        target.server_close()
        redirect_thread.join(timeout=2)
        target_thread.join(timeout=2)


def test_worker_loader_rejects_insecure_remote_url_without_echoing_token():
    secret = "private-worker-token"
    raw = json.dumps({"peer": {"url": "http://worker.example", "token": secret}})
    with pytest.raises(ValueError) as exc:
        load_workers(raw)
    assert "HTTPS" in str(exc.value)
    assert secret not in str(exc.value)
    assert secret not in repr(load_workers(json.dumps({"local": {
        "url": "http://127.0.0.1:8765", "token": secret,
    }})))


def test_worker_rejects_urls_with_credentials_paths_queries_or_fragments():
    for url in (
        "https://user:pass@worker.example",
        "https://worker.example/extra",
        "https://worker.example?token=x",
        "https://worker.example#fragment",
    ):
        with pytest.raises(ValueError):
            WorkerClient("bad", url, "test-token")
    with pytest.raises(ValueError, match="path"):
        WorkerClient("local", "http://127.0.0.1:8765", "test-token").request("/api/../health")
    with pytest.raises(ValueError, match="GET or POST"):
        WorkerClient("local", "http://127.0.0.1:8765", "test-token").request("/api/health", "DELETE")
