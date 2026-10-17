"""Authenticated client for a configured remote Dagi worker."""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        # Never forward a worker's bearer token to a redirect target.
        return None


@dataclass(frozen=True)
class WorkerClient:
    name: str
    url: str
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.name):
            raise ValueError("worker name must contain only letters, digits, '_' or '-' (max 64)")
        if not isinstance(self.token, str) or not self.token:
            raise ValueError("worker token is required")
        if not isinstance(self.url, str):
            raise ValueError("worker URL must be text")
        parsed = urlparse(self.url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("worker URL must be an HTTP(S) origin without credentials, query, or fragment")
        try:
            parsed.port  # Force invalid port syntax to fail during configuration loading.
        except ValueError as exc:
            raise ValueError("worker URL has an invalid port") from exc
        if parsed.path not in {"", "/"}:
            raise ValueError("worker URL must not include a path")
        if parsed.scheme == "http":
            try:
                loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                loopback = parsed.hostname.lower() == "localhost"
            if not loopback:
                raise ValueError(
                    "remote worker token transport requires HTTPS; HTTP is allowed only for loopback or SSH tunnels"
                )

    def request(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        if (
            not isinstance(path, str)
            or not path.startswith("/api/")
            or "?" in path
            or "#" in path
            or ".." in path
        ):
            raise ValueError("invalid worker API path")
        if method not in {"GET", "POST"}:
            raise ValueError("worker method must be GET or POST")
        if body is not None and not isinstance(body, dict):
            raise ValueError("worker request body must be an object")
        request = Request(
            self.url.rstrip("/") + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with build_opener(_NoRedirect).open(request, timeout=15) as response:
                data = response.read(8_000_001)
                if len(data) > 8_000_000:
                    raise ValueError("worker response exceeds 8 MB")
                decoded = json.loads(data)
                if not isinstance(decoded, dict):
                    raise ValueError("worker returned a non-object response")
                return decoded
        except HTTPError as exc:
            # Do not include the response body or request headers in the error.
            raise ValueError(f"worker returned HTTP {exc.code}") from None


def load_workers(raw: str) -> dict[str, WorkerClient]:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("DAGI_WORKERS must be valid JSON") from exc
    if not isinstance(values, dict):
        raise ValueError("DAGI_WORKERS must be an object")
    workers = {}
    for name, config in values.items():
        if not isinstance(config, dict) or set(config) != {"url", "token"}:
            raise ValueError("each DAGI_WORKERS entry must contain exactly url and token")
        try:
            workers[name] = WorkerClient(name, config["url"], config["token"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid worker configuration for {name!r}: {exc}") from None
    return workers
