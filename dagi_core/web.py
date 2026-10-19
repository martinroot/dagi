"""Loopback-only visual sandbox backed by the existing SQLite agent state."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .agent import Agent, SYSTEM_PROMPT
from .auth import create_session_token, verify_password, verify_session_token
from .config import Config, load_config
from .context import ContextBuilder
from .delegation import DelegationManager
from .provider import OpenAICompatibleProvider
from .runtime import RuntimeLease
from .runtime_context import extract_runtime_context
from .state import StateStore, goal_lesson_fingerprint
from .tools import ToolRegistry, _resolve
from .workspace import resolve_session_workspace
from .goals import validate_checks, verify
from .worker import load_workers
from game.world import links as game_links
from game.bridge import GAME_PROMPT, identity as game_identity, register_game, render_game_context
from game.turns import GameContext, game_call_cap
from game.life import LifeRuntime
from game.learning import summary as learning_summary
from game.store import GameStore, live_slot
from game.world import PAIRS, frame as game_frame, observation as game_observation
from game.studio import browser_report, build_summary, human_prompt, digest as game_digest, snapshot as game_snapshot, configuration as game_configuration

ProviderFactory = Callable[[str, str, str], Any]
_REFLECTION_VOLATILE_KEYS = {"timestamp", "created_at", "updated_at", "request_id", "event_id", "nonce"}


def _normalize_reflection_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_reflection_value(item)
            for key, item in sorted(value.items())
            if str(key).lower() not in _REFLECTION_VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_normalize_reflection_value(item) for item in value]
    return value


def _reflection_fingerprint(value: Any) -> str:
    serialized = json.dumps(
        _normalize_reflection_value(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _runtime_inspector_status(state: StateStore, session_id: int, run_id: str | None = None) -> dict[str, Any]:
    """Build an allowlisted, read-only inspection summary from this session's persisted rows."""
    run = state.get_run(run_id) if run_id else None
    if run_id and (run is None or run["session_id"] != session_id):
        return {}
    if run is None:
        runs = state.list_runs(session_id, 20)
        run = runs[0] if runs else None
        run_id = run["run_id"] if run else None

    runtime: dict[str, Any] = {}
    if run_id:
        for call in reversed(state.list_provider_calls(run_id)):
            if call["purpose"] != "agent":
                continue
            request = state.get_provider_request(call["id"])
            messages = request.get("messages", []) if isinstance(request, dict) else []
            for message in messages:
                if isinstance(message, dict) and message.get("role") == "system":
                    parsed = extract_runtime_context(message.get("content", ""))
                    if parsed is not None:
                        runtime = parsed
                        break
            if runtime:
                break

    goals = state.list_goals(session_id)
    goal = next((item for item in goals if run_id and run_id in item["runs"]), None)
    if goal is None and run_id is None and goals:
        goal = goals[0]

    goal_reflection = goal["reflections"][-1] if goal and goal.get("reflections") else None
    tool_reflections = state.list_tool_reflections(session_id, limit=3)
    tool_reflection = next(
        (item for item in tool_reflections if item["run_id"] == run_id),
        tool_reflections[0] if run_id is None and tool_reflections else None,
    )
    candidates = [item for item in (goal_reflection, tool_reflection) if item]
    reflection = max(candidates, key=lambda item: item.get("created_at", "")) if candidates else None

    def short(value: Any, limit: int = 512) -> str | None:
        return value[:limit] if isinstance(value, str) else None

    goal_summary = short(goal.get("status"), 32) if goal else None
    latest_reflection = None
    blocker = None
    next_action = None
    recovery_guidance = None
    last_evidence: list[str] = []
    check_result = None
    lessons: list[dict[str, Any]] = []
    if goal:
        if goal_reflection:
            observed = goal_reflection.get("observed", {})
            check_result = {
                "observed_passed": observed.get("passed") if isinstance(observed, dict) else None,
                "followup_passed": goal_reflection.get("following_check_passed"),
                "detail": short(observed.get("detail"), 256) if isinstance(observed, dict) else None,
            }
        for check in goal.get("checks", []):
            if len(lessons) >= 3:
                break
            check_type = check.get("type")
            check_key = (
                Path(check["argv"][0]).name[:128]
                if check_type == "command" and isinstance(check.get("argv"), list) and check["argv"]
                else str(check.get("path", ""))[:256]
            )
            if not check_type or not check_key:
                continue
            for item in state.list_goal_lessons(
                session_id, check_type=check_type, check_key=check_key,
                limit=3 - len(lessons),
            ):
                lessons.append({
                    "check_type": short(item.get("check_type"), 32),
                    "check_key": short(item.get("check_key"), 256),
                    "status": short(item.get("status"), 16),
                    "lesson": short(item.get("lesson"), 512),
                    "support_count": item.get("support_count"),
                    "evidence_ids": [short(value, 128) for value in item.get("evidence_ids", [])[:3]],
                })

    if reflection:
        is_goal_reflection = "expected" in reflection and "observed" in reflection
        if is_goal_reflection:
            observed = reflection.get("observed", {})
            latest_reflection = {
                "trigger": short(reflection.get("trigger"), 64) or "unknown",
                "observed": {
                    key: observed.get(key)
                    for key in ("passed", "detail")
                    if isinstance(observed, dict) and isinstance(observed.get(key), (str, bool))
                },
                "evidence_ids": [short(value, 128) for value in reflection.get("evidence_ids", [])[:4]],
                "cause_hypothesis": short(reflection.get("cause_hypothesis"), 512),
                "next_change": short(reflection.get("next_change"), 512),
                "following_check_passed": reflection.get("following_check_passed"),
                "repeat_count": reflection.get("repeat_count"),
                "blocker": bool(reflection.get("blocker")),
            }
            last_evidence = latest_reflection["evidence_ids"]
            if reflection.get("blocker"):
                blocker = "Repeated check/action failure threshold reached"
            elif reflection.get("following_check_passed") is True:
                blocker = None
            elif reflection.get("following_check_passed") is False:
                blocker = "Follow-up acceptance check still failed"
            elif isinstance(observed, dict) and observed.get("passed") is False:
                blocker = short(observed.get("detail"), 256) or "Acceptance check failed"
            next_action = short(reflection.get("next_change"))
        else:
            observed = reflection.get("observed", {})
            latest_reflection = {
                "trigger": short(reflection.get("trigger"), 64),
                "tool_name": short(reflection.get("tool_name"), 64),
                "observed": {
                    key: observed.get(key)
                    for key in ("outcome", "repeat_count", "provider_turn_completed", "goal_status", "successful_tool_count", "known_failure_count")
                    if isinstance(observed, dict) and isinstance(observed.get(key), (str, int, bool))
                },
                "evidence_ids": [short(value, 128) for value in reflection.get("evidence_ids", [])[:4]],
                "repeat_count": reflection.get("repeat_count"),
                "blocker": bool(reflection.get("blocker")),
                "run_id": short(reflection.get("run_id"), 128),
            }
            last_evidence = latest_reflection["evidence_ids"]
            if reflection.get("blocker"):
                blocker = "Repeated known tool failure threshold reached"
                recovery_guidance = "Choose a materially different action or report a blocker"
            elif reflection.get("trigger") == "run_concluded":
                recovery_guidance = "Check acceptance/goal status; provider-turn completion is not goal completion"

    if not last_evidence:
        progress = runtime.get("progress", {})
        raw_evidence = progress.get("evidence_ids", []) if isinstance(progress, dict) else []
        if isinstance(raw_evidence, list):
            last_evidence = [short(item, 128) for item in raw_evidence[:4] if isinstance(item, str)]

    tool_outcome = None
    if run_id:
        run_tools = [call for call in state.list_tool_calls(session_id) if call["run_id"] == run_id]
        if run_tools:
            tool_outcome = {
                "tool_name": short(run_tools[-1].get("name"), 64),
                "status": short(run_tools[-1].get("status"), 16),
            }

    identity = runtime.get("identity", {})
    assignment = runtime.get("assignment", {})
    environment = runtime.get("environment", {})
    progress = runtime.get("progress", {})
    return {
        "role": short(identity.get("role"), 64) if isinstance(identity, dict) else None,
        "agent": short(identity.get("agent_name"), 64) if isinstance(identity, dict) else None,
        "assignment": short(assignment.get("my_task"), 512) if isinstance(assignment, dict) else None,
        "purpose": short(assignment.get("purpose"), 512) if isinstance(assignment, dict) else None,
        "required_output": short(assignment.get("required_output"), 256) if isinstance(assignment, dict) else None,
        "acceptance_check_ids": [short(item, 128) for item in assignment.get("acceptance_check_ids", [])[:12] if isinstance(item, str)]
        if isinstance(assignment, dict) and isinstance(assignment.get("acceptance_check_ids"), list) else None,
        "workspace": short(environment.get("workspace"), 256) if isinstance(environment, dict) else None,
        "phase": short(progress.get("phase"), 64) if isinstance(progress, dict) else None,
        "last_evidence": last_evidence,
        "blocker": blocker,
        "next_action": next_action,
        "recovery_guidance": recovery_guidance,
        "latest_reflection": latest_reflection,
        "lessons": lessons,
        "tool_outcome": tool_outcome,
        "check_result": check_result,
        "goal_status": goal_summary,
    }


@dataclass
class _RunControl:
    session_id: int
    cancellation: Event = field(default_factory=Event)
    thread: Thread | None = None
    providers: list[Any] = field(default_factory=list)


class WebApp:
    """A threaded HTTP shell; each request/worker opens its own SQLite connection."""

    def __init__(self, config: Config, provider_factory: ProviderFactory | None = None):
        if not config.web_username or not config.web_password_hash:
            raise ValueError("DAGI_WEB_USERNAME and DAGI_WEB_PASSWORD_HASH are required for dagi-web")
        if (
            not config.web_cookie_path.startswith("/")
            or ";" in config.web_cookie_path
            or "\r" in config.web_cookie_path
            or "\n" in config.web_cookie_path
        ):
            raise ValueError("DAGI_WEB_COOKIE_PATH must be an absolute cookie path")
        self.config = config
        self.provider_factory = provider_factory or OpenAICompatibleProvider
        self.agent_id = str(uuid4())
        self._runs: dict[str, _RunControl] = {}
        self._goals: dict[str, _RunControl] = {}
        self._lock = Lock()
        self._lease: RuntimeLease | None = None
        self._session_secret = secrets.token_bytes(32)
        self._revoked_sessions: dict[str, int] = {}
        self._failed_logins: dict[str, tuple[int, float]] = {}
        self.life = LifeRuntime(self)
        self.workers = load_workers(os.environ.get("DAGI_WORKERS", "{}"))

    def _cookie_token(self, headers: Any) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("Cookie", ""))
            return cookie["dagi_session"].value if "dagi_session" in cookie else None
        except Exception:
            return None

    def _is_authenticated(self, headers: Any) -> bool:
        bearer = headers.get("Authorization", "")
        if self.config.web_token and hmac.compare_digest(
            bearer, "Bearer " + self.config.web_token
        ):
            return True
        token = self._cookie_token(headers)
        if not token or not verify_session_token(
            token, self.config.web_username, self._session_secret
        ):
            return False
        now = int(time.time())
        with self._lock:
            for revoked, expiry in list(self._revoked_sessions.items()):
                if expiry <= now:
                    del self._revoked_sessions[revoked]
            return token not in self._revoked_sessions

    def _origin_allowed(self, headers: Any) -> bool:
        origin = headers.get("Origin")
        expected = self.config.web_public_origin
        return not origin or not expected or origin.rstrip("/") == expected

    def _login_blocked(self, remote_addr: str) -> bool:
        now = time.monotonic()
        with self._lock:
            attempts, blocked_until = self._failed_logins.get(remote_addr, (0, 0.0))
            if blocked_until > now:
                return True
            if blocked_until:
                self._failed_logins.pop(remote_addr, None)
        return False

    def _failed_login(self, remote_addr: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts, blocked_until = self._failed_logins.get(remote_addr, (0, 0.0))
            if blocked_until > now:
                return
            attempts += 1
            self._failed_logins[remote_addr] = (0, now + 60.0) if attempts >= 5 else (attempts, 0.0)

    def _successful_login(self, remote_addr: str) -> None:
        with self._lock:
            self._failed_logins.pop(remote_addr, None)

    def _revoke_session(self, token: str) -> None:
        with self._lock:
            self._revoked_sessions[token] = int(time.time()) + 43_200

    @staticmethod
    def _cancel_control(control: _RunControl) -> None:
        control.cancellation.set()
        for provider in tuple(control.providers):
            cancel = getattr(provider, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass

    def close(self) -> None:
        self.life.close()
        with self._lock:
            controls = list({id(item): item for item in [*self._runs.values(), *self._goals.values()]}.values())
        for control in controls:
            self._cancel_control(control)
        for control in controls:
            if control.thread is not None:
                control.thread.join(timeout=3)
        if all(control.thread is None or not control.thread.is_alive() for control in controls):
            if self._lease is not None:
                self._lease.close()
                self._lease = None

    def create_server(self, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
        if self._lease is not None:
            raise ValueError("this WebApp already owns a runtime lease")
        lease = RuntimeLease(self.config.home)
        self._lease = lease
        try:
            with _StateContext(StateStore(self.config.database)) as state:
                state.recover_interrupted()
                state.recover_goals()
            with GameStore(self.config.database) as game:
                game.recover_releases()
            self.life.recover()
        except BaseException:
            lease.close()
            self._lease = None
            raise
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def _send_json(
                self, status: int, payload: Any, headers: dict[str, str] | None = None
            ) -> None:
                data = json.dumps(_json_safe(payload), ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
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
                    if path == "/game":
                        self.send_response(302)
                        self.send_header("Location", "game/")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    if path in {"/", "/app.js", "/game", "/game/", "/game/game.js", "/game/studio.js", "/game/scene.js", "/game/anatomy.js", "/game/vector.js", "/game/scenery.js", "/game/learning.js", "/game/direction.js", "/game/workshop.js", "/game/component-host.js"}:
                        self._static(path)
                    elif path == "/api/auth/session":
                        if app._is_authenticated(self.headers):
                            self._send_json(200, {"authenticated": True})
                        else:
                            self._send_json(401, {"error": "authentication required"})
                    elif path.startswith("/api/") and not app._is_authenticated(self.headers):
                        self._send_json(401, {"error": "authentication required"})
                    elif path == "/api/health":
                        self._send_json(200, {
                            "healthy": True,
                            "active_runs": len(app._runs),
                            "active_goals": len(app._goals),
                        })
                    elif path == "/api/workers":
                        self._send_json(200, {"workers": [
                            {"id": name, "url": worker.url}
                            for name, worker in app.workers.items()
                        ]})
                    elif match := re.fullmatch(r"/api/workers/([A-Za-z0-9_-]+)/proxy(/api/.*)", path):
                        self._proxy(match.group(1), match.group(2))
                    elif path == "/api/game/sessions":
                        with GameStore(app.config.database) as game:
                            self._send_json(200, {"sessions": game.list_sessions()})
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/frames", path):
                        self._game_frames(int(match.group(1)))
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/export", path):
                        session_id = int(match.group(1))
                        with GameStore(app.config.database) as game:
                            world = game.get(session_id)
                        if world is None:
                            self._send_json(404, {"error": "game session not found"})
                            return
                        with _StateContext(self._state()) as state:
                            try:
                                export = _game_session_export(state, session_id, world)
                            except ValueError as exc:
                                self._send_json(404, {"error": str(exc)})
                                return
                        serialized = json.dumps(_json_safe(export), ensure_ascii=False).encode("utf-8")
                        if len(serialized) > 50_000_000:
                            self._send_json(413, {"error": "session export exceeds 50 MB; no partial export was produced"})
                            return
                        self._send_json(200, export, headers={
                            "Content-Disposition": f'attachment; filename="dagi-session-{session_id}.json"',
                        })
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)", path):
                        session_id = int(match.group(1))
                        with GameStore(app.config.database) as game:
                            world = game.get(session_id)
                        if world is None:
                            self._send_json(404, {"error": "game session not found"})
                            return
                        with _StateContext(self._state()) as state:
                            session = state.get_session(session_id)
                            runs = state.list_runs(session_id, 10)
                            active = next((r for r in runs if r["status"] == "running"), None)
                            reference = active or (runs[0] if runs else None)
                            calls = state.list_provider_calls(reference["run_id"]) if reference else []
                            pending = next((c for c in reversed(calls) if c["finished_at"] is None), None) if active else None
                            executing = next((c for c in reversed(state.list_tool_calls(session_id)) if c["status"] == "running" and c["run_id"] == active["run_id"]), None) if active else None
                            activity = {"phase": "tool" if executing else "provider" if pending else "running" if active else "idle",
                                        "model": pending["model"] if pending else app.config.model, "provider_calls": len(calls), "run_id": active["run_id"] if active else None,
                                        "tool": executing["name"] if executing else None}
                        workspace = resolve_session_workspace(app.config.workspace, session["workspace"])
                        self._send_json(200, {"self": game_identity(session_id, workspace, world),
                            "scene": game_observation(world), "frame": game_frame(world),
                            "links": game_links(world), "motion": world["motion"], "history": world["history"],
                            "reflections": world["reflections"], "widgets": world["widgets"], "components": world["components"], "theme": world["theme"],
                            "learning":learning_summary(world,details=True), "character":world["character"], "art":world["art"], "body_control":world["body_control"], "environment":world["environment"], "ropes":world["ropes"], "substances":world["substances"], "direction":world["direction"], "appendages":world["appendages"], "projects":[{"name":k,"version":v["version"],"description":v["description"]} for k,v in world["projects"].items()],
                            "life": world["life"], "policies": [{"name": k, "version": v["version"], "description": v["description"]} for k,v in world["policies"].items()], "appearance": world["appearance"], "evolution": world["evolution"],
                            "build": build_summary(world), "preview": {k: world["draft"]["candidate"][k] for k in ("widgets", "objects", "components")} if world["draft"] else None,
                            "last_release": world["last_release"], "activity": activity, "server_time": time.time(),
                            "render_key": game_digest(game_configuration({**world,**world["draft"]["candidate"]}) if world["draft"] else game_configuration(world))})
                    elif path == "/api/sessions":
                        with _StateContext(self._state()) as state:
                            sessions = state.list_sessions(100)
                            for session in sessions:
                                session["runs"] = state.list_runs(session["id"], 20)
                                session["goals"] = state.list_goals(session["id"])
                            self._send_json(200, {"sessions": sessions})
                    elif match := re.fullmatch(r"/api/sessions/(\d+)", path):
                        session_id = int(match.group(1))
                        with _StateContext(self._state()) as state:
                            snapshot = state.session_snapshot(session_id)
                            if snapshot is None:
                                self._send_json(404, {"error": "session not found"})
                                return
                            snapshot["runtime_status"] = _runtime_inspector_status(state, session_id)
                            self._send_json(200, snapshot)
                    elif match := re.fullmatch(r"/api/goals/([^/]+)", path):
                        with _StateContext(self._state()) as state:
                            goal = state.get_goal(match.group(1))
                            if goal is None:
                                self._send_json(404, {"error": "goal not found"})
                                return
                            self._send_json(200, {"goal": goal})
                    elif match := re.fullmatch(r"/api/runs/([^/]+)/events", path):
                        if parse_qs(parsed.query).get("format") == ["json"]:
                            self._event_page(match.group(1), parsed.query)
                        else:
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
                    if not app._origin_allowed(self.headers):
                        self._send_json(403, {"error": "request origin is not allowed"})
                        return
                    if parsed.path == "/api/auth/login":
                        remote_addr = self.headers.get("X-Real-IP", self.client_address[0])
                        if app._login_blocked(remote_addr):
                            self._send_json(429, {"error": "too many login attempts"}, {"Retry-After": "60"})
                            return
                        username = body.get("username")
                        password = body.get("password")
                        valid_user = isinstance(username, str) and hmac.compare_digest(
                            username.encode("utf-8"), app.config.web_username.encode("utf-8")
                        )
                        valid_password = isinstance(password, str) and len(password) <= 4096 and verify_password(
                            password, app.config.web_password_hash
                        )
                        if not valid_user or not valid_password:
                            app._failed_login(remote_addr)
                            self._send_json(401, {"error": "invalid username or password"})
                            return
                        app._successful_login(remote_addr)
                        token = create_session_token(app.config.web_username, app._session_secret)
                        cookie = (
                            f"dagi_session={token}; Path={app.config.web_cookie_path}; "
                            "HttpOnly; SameSite=Strict; Max-Age=43200"
                        )
                        if app.config.web_cookie_secure:
                            cookie += "; Secure"
                        self._send_json(
                            200,
                            {"authenticated": True},
                            {"Set-Cookie": cookie},
                        )
                    elif parsed.path == "/api/auth/logout":
                        token = app._cookie_token(self.headers)
                        if token and app._is_authenticated(self.headers):
                            app._revoke_session(token)
                        cookie = (
                            f"dagi_session=; Path={app.config.web_cookie_path}; "
                            "HttpOnly; SameSite=Strict; Max-Age=0"
                        )
                        if app.config.web_cookie_secure:
                            cookie += "; Secure"
                        self._send_json(200, {"authenticated": False}, {"Set-Cookie": cookie})
                    elif parsed.path.startswith("/api/") and not app._is_authenticated(self.headers):
                        self._send_json(401, {"error": "authentication required"})
                    elif match := re.fullmatch(r"/api/workers/([A-Za-z0-9_-]+)/proxy(/api/.*)", parsed.path):
                        self._proxy(match.group(1), match.group(2), body)
                    elif match := re.fullmatch(r"/api/sessions/(\d+)/goals", parsed.path):
                        self._send_json(202, app.start_goal(int(match.group(1)), body))
                    elif match := re.fullmatch(r"/api/goals/([^/]+)/(stop|resume)", parsed.path):
                        self._send_json(202, app.control_goal(match.group(1), match.group(2)))
                    elif parsed.path == "/api/game/sessions":
                        title = body.get("title", "Embodied experiment")
                        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
                            raise ValueError("title must be 1..160 characters")
                        workspace = f"game/sessions/{uuid4().hex}"
                        with _StateContext(self._state()) as state:
                            session_id = state.create_session(title, workspace=workspace)
                        with GameStore(app.config.database) as game:
                            mode=body.get("mode","physical")
                            if mode not in ("physical","assisted"):raise ValueError("mode must be physical or assisted")
                            game.create(session_id,mode=mode)
                        self._send_json(201, {"session_id": session_id})
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/learning/evaluate", parsed.path):
                        from game.world import keys as game_keys
                        from game.learning import handle as train_skill
                        game_keys(body,("skill","world_version","contract"))
                        if type(body.get("world_version")) is not int or not isinstance(body.get("contract"),str):raise ValueError("evaluation requires the displayed world/contract versions")
                        session_id=int(match.group(1))
                        if app._session_busy(session_id):raise ValueError("wait for the current model turn before evaluating manually")
                        result=train_skill(app.config.database,session_id,{"action":"evaluate",**body})
                        self._send_json(200,{"local":True,"model_calls":0,**result})
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/project-event", parsed.path):
                        session_id=int(match.group(1))
                        from game.world import keys as game_keys
                        game_keys(body,("version","id"))
                        if not isinstance(body.get("id"),str) or not 1<=len(body["id"])<=60:raise ValueError("event id must be1..60 characters")
                        with GameStore(app.config.database) as game:
                            with game.transient(session_id) as world:
                                if type(body.get("version")) is not int or body["version"]!=world["version"] or not world["active_project"]:raise ValueError("project changed; refresh before sending event")
                                world["event_queue"]=(world["event_queue"]+[{"id":body["id"],"tick":world["tick"]}])[-8:]
                        self._send_json(200,{"queued":True,"local":True})
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/vision", parsed.path):
                        session_id=int(match.group(1))
                        with GameStore(app.config.database) as game:
                            if game.get(session_id) is None:raise ValueError("game session not found")
                        slot=live_slot(app.config.database,session_id)
                        if body.get("enabled") is False:
                            with slot.lock:slot.vision=None
                        else:
                            image=body.get("image","")
                            if not isinstance(image,str) or not image.startswith("data:image/jpeg;base64,") or len(image)>150000:
                                raise ValueError("vision requires a bounded JPEG data URL")
                            raw=base64.b64decode(image.split(",",1)[1],validate=True)
                            if not raw.startswith(b"\xff\xd8") or len(raw)>100000:raise ValueError("invalid JPEG frame")
                            if type(body.get("version")) is not int:raise ValueError("vision requires world version")
                            with slot.lock:slot.vision={"image":image,"version":body["version"],"at":time.time()}
                        self._send_json(200,{"saved":True})
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/input", parsed.path):
                        session_id=int(match.group(1))
                        with GameStore(app.config.database) as game:
                            with game.transient(session_id) as world:
                                kind=body.get("type")
                                if kind=="grab":
                                    from game.world import number
                                    number(body.get("x"),0,1000,"x");number(body.get("y"),0,600,"y")
                                    if not any(o["id"]==body.get("id") and o["kind"]=="body" and o.get("motion")!="static" for o in world["objects"]):raise ValueError("unknown dynamic object")
                                    world["human"].update(object=body["id"],pointer=[body["x"],body["y"]])
                                elif kind=="release":
                                    world["human"].pop("object",None);world["human"].pop("pointer",None)
                                elif kind=="muscle":
                                    from game.embodiment import limits
                                    from game.world import number
                                    if body.get("joint") not in limits(world):raise ValueError("unknown muscle joint")
                                    value=number(body.get("effort"),-1,1,"effort")
                                    world["human"].update(muscles={body["joint"]:value},until=world["tick"]+18)
                                elif kind=="drive":
                                    from game.world import number
                                    number(body.get("drive",0),-1,1,"drive")
                                    if type(body.get("jump",False)) is not bool:raise ValueError("jump must be boolean")
                                    if world["body_control"]["mode"]=="physical":raise ValueError("physical mode uses muscle input, not automatic drive or jump")
                                    world["human"].update(drive=body.get("drive",0),jump=body.get("jump",False),until=world["tick"]+30)
                                else:raise ValueError("input type must be grab, release or drive")
                        app.life.ensure_clock(session_id)
                        self._send_json(200,{"accepted":True})
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/life", parsed.path):
                        self._send_json(200, app.life.control(int(match.group(1)), body))
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/interact", parsed.path):
                        session_id = int(match.group(1))
                        with GameStore(app.config.database) as game:
                            world = game.get(session_id)
                            if world is None:
                                raise ValueError("game session not found")
                            prompt = human_prompt(world, body)
                            widget=next((w for w in world["widgets"] if w["id"]==body.get("widget_id")),None)
                            target=widget.get("target") if widget else None
                            if body.get("component_id"):
                                component=next((c for c in world["components"] if c["id"]==body["component_id"]),None)
                                event=next((e for e in component.get("events",[]) if e["id"]==body.get("event_id")),None) if component else None
                                target=event.get("target") if event else None
                        if target and target.get("type")=="project":
                            if world["active_project"]!=target["name"]:
                                app.life.control(session_id,{"action":"select","name":target["name"]})
                            if target.get("event"):
                                with GameStore(app.config.database) as game:
                                    with game.transient(session_id) as world:
                                        if body["version"]!=world["version"] or world["active_project"]!=target["name"]:raise ValueError("project changed; refresh before sending event")
                                        world["event_queue"]=(world["event_queue"]+[{"id":target["event"],"tick":world["tick"]}])[-8:]
                            app.life.ensure_clock(session_id)
                            self._send_json(200,{"local":True,"project":target["name"]})
                        elif target and target.get("type")=="policy":
                            app.life.control(session_id,{"action":"select","name":target["name"]})
                            app.life.ensure_clock(session_id)
                            self._send_json(200,{"local":True,"policy":target["name"]})
                        else:self._start_run(session_id, {"message": prompt})
                    elif match := re.fullmatch(r"/api/game/sessions/(\d+)/render-report", parsed.path):
                        with GameStore(app.config.database) as game:
                            game.apply(int(match.group(1)), browser_report, body)
                        self._send_json(200, {"saved": True})
                    elif parsed.path == "/api/sessions":
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
                except RuntimeError as exc:
                    self._send_json(409, {"error": str(exc)})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._send_json(400, {"error": str(exc)})
                except Exception:
                    self._send_json(500, {"error": "sandbox request failed"})

            def _proxy(self, worker_id: str, path: str, body: dict[str, Any] | None = None) -> None:
                worker = app.workers.get(worker_id)
                allowed = re.fullmatch(
                    r"/api/(?:health|sessions|sessions/\d+(?:/(?:runs|goals))?|runs/[^/]+(?:/events|/cancel)?|goals/[^/]+(?:/(?:stop|resume))?)",
                    path,
                )
                if worker is None or not allowed:
                    self._send_json(404, {"error": "worker or endpoint not found"})
                    return
                try:
                    result = worker.request(path, "POST" if body is not None else "GET", body)
                except Exception:
                    # The peer response may contain sensitive material; do not relay it.
                    self._send_json(502, {"error": "worker request failed"})
                    return
                self._send_json(200, result)

            def _static(self, path: str) -> None:
                is_game = path.startswith("/game")
                name = (path.rsplit("/", 1)[-1] if path.endswith(".js") else "index.html") if is_game else ("index.html" if path == "/" else "app.js")
                content_type = "text/html; charset=utf-8" if name.endswith(".html") else "text/javascript; charset=utf-8"
                data = files("game" if is_game else "dagi_core").joinpath("static", name).read_bytes()
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
                        "parent": state.get_run(run["parent_run_id"]) if run["parent_run_id"] else None,
                        "usage": state.usage_summary(run_id),
                        "budget_usage": state.usage_summary_for_budget(run_id),
                        "provider_calls": provider_calls,
                        "requests": requests,
                        "tool_calls": tool_calls,
                        "children": state.list_child_runs(run_id),
                        "messages": state.message_records(run["session_id"]),
                        "event_count": len(state.list_run_events(run_id, limit=5000)),
                        "runtime_status": _runtime_inspector_status(state, run["session_id"], run_id),
                    })

            def _event_page(self, run_id: str, query: str) -> None:
                params = parse_qs(query)
                if "through" not in params:
                    raise ValueError("a through cursor is required for event paging")
                after = int(params.get("after", ["0"])[0])
                through = int(params["through"][0])
                limit = int(params.get("limit", ["500"])[0])
                if after < 0 or through < 0 or not 1 <= limit <= 1000:
                    raise ValueError("event cursors must be non-negative and page size must be 1..1000")
                with _StateContext(self._state()) as state:
                    if state.get_run(run_id) is None:
                        self._send_json(404, {"error": "run not found"})
                        return
                    rows = state.list_run_events(
                        run_id, after_id=after, through_id=through, limit=limit + 1
                    )
                    events = rows[:limit]
                    self._send_json(200, {
                        "run_id": run_id,
                        "through": through,
                        "events": events,
                        "has_more": len(rows) > limit,
                        "next_after": events[-1]["id"] if events else after,
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

            def _game_frames(self, session_id):
                with GameStore(app.config.database) as game:
                    if game.get(session_id) is None:
                        self._send_json(404, {"error":"game session not found"})
                        return
                slot = live_slot(app.config.database, session_id)
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type","text/event-stream; charset=utf-8")
                self.send_header("Cache-Control","no-cache, no-transform")
                self.send_header("X-Accel-Buffering","no")
                self.end_headers()
                revision = -1
                try:
                    while not app.life._stop.is_set():
                        with slot.lock:
                            w = slot.world
                            packet = {"revision":w["revision"],"version":w["version"],"frame":game_frame(w),
                                      "emotion":w["emotion"],"life":w["life"],"contacts":w["contacts"],
                                      "error":w["policy_error"],"release":{k:w["draft"][k] for k in ("id","state","objective","edits","activate_at","countdown_ms") if k in w["draft"]} if w["draft"] else None} if w["revision"]!=revision else None
                        if packet:
                            self.wfile.write(("data: "+json.dumps(packet,separators=(",",":"))+"\n\n").encode())
                            self.wfile.flush()
                            revision = packet["revision"]
                        time.sleep(1/30)
                except (BrokenPipeError,ConnectionResetError):
                    return

            def _start_run(self, session_id: int, body: dict[str, Any]) -> None:
                self._send_json(202, app.start_run(session_id, body.get("message")))

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

        class OwnedServer(ThreadingHTTPServer):
            daemon_threads = True

            def server_close(self) -> None:
                app.close()
                super().server_close()

        try:
            return OwnedServer((host, port), Handler)
        except BaseException:
            app.close()
            raise

    def start_run(self, session_id: int, message: str) -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be non-empty text")
        with self._lock:
            if self._session_busy(session_id):
                raise RuntimeError("a run is already active for this session")
            with _StateContext(StateStore(self.config.database)) as state:
                if state.get_session(session_id) is None:
                    raise ValueError("session not found")
                run_id = state.create_run(session_id, agent_id=self.agent_id, agent_name=self.config.model)
            control = _RunControl(session_id)
            self._runs[run_id] = control
            control.thread = Thread(target=self._execute_run, args=(run_id, session_id, message, control), daemon=True)
            control.thread.start()
        return {"run_id": run_id, "session_id": session_id, "status": "running"}

    def _session_busy(self, session_id: int) -> bool:
        return any(
            control.session_id == session_id
            for control in [*self._runs.values(), *self._goals.values()]
        )

    def start_goal(self, session_id: int, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ValueError("goal request must be a JSON object")
        allowed_fields = {"objective", "checks", "max_iterations"}
        extra_fields = set(body) - allowed_fields
        if extra_fields:
            raise ValueError("goal capability settings are operator-configured, not request fields")
        objective = body.get("objective")
        cap = body.get("max_iterations", 5)
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 8_000:
            raise ValueError("objective must be non-empty text of at most 8000 characters")
        if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= 10:
            raise ValueError("max_iterations must be 1..10")
        checks = validate_checks(body.get("checks"))
        if any(check["type"] == "command" for check in checks) and not self.config.enable_check_commands:
            raise ValueError("command checks are disabled by operator configuration")

        with self._lock, _StateContext(StateStore(self.config.database)) as state:
            session = state.get_session(session_id)
            if session is None:
                raise ValueError("session not found")
            workspace = resolve_session_workspace(self.config.workspace, session["workspace"])
            workspace.mkdir(parents=True, exist_ok=True)
            for check in checks:
                if check["type"] != "command":
                    _resolve(workspace, check["path"])
            if self._session_busy(session_id):
                raise RuntimeError("a run or goal is already active for this session")
            goal_id = state.create_goal(session_id, objective, checks, cap)
            self._launch_goal(goal_id, session_id)
            created = state.get_goal(goal_id)
            if created is None:
                raise RuntimeError("created goal could not be read back")
            return created

    def _launch_goal(self, goal_id: str, session_id: int) -> None:
        control = _RunControl(session_id)
        self._goals[goal_id] = control
        control.thread = Thread(target=self._drive_goal, args=(goal_id, control), daemon=True)
        control.thread.start()

    def control_goal(self, goal_id: str, action: str) -> dict[str, Any]:
        if action not in {"stop", "resume"}:
            raise ValueError("goal action must be stop or resume")
        if action == "stop":
            with self._lock:
                control = self._goals.get(goal_id)
            if control is not None:
                self._cancel_control(control)
            with _StateContext(StateStore(self.config.database)) as state:
                goal = state.get_goal(goal_id)
                if goal is None:
                    raise ValueError("goal not found")
                if control is None and goal["status"] == "running":
                    state.update_goal(goal_id, "interrupted")
                updated = state.get_goal(goal_id)
                if updated is None:
                    raise RuntimeError("goal disappeared while stopping")
                return updated

        with self._lock, _StateContext(StateStore(self.config.database)) as state:
            goal = state.get_goal(goal_id)
            if goal is None:
                raise ValueError("goal not found")
            if goal["status"] not in {"interrupted", "error"}:
                raise ValueError("only interrupted or error goals can resume")
            if self._session_busy(goal["session_id"]):
                raise RuntimeError("a run or goal is already active for this session")
            state.update_goal(goal_id, "running")
            self._launch_goal(goal_id, goal["session_id"])
            updated = state.get_goal(goal_id)
            if updated is None:
                raise RuntimeError("goal disappeared while resuming")
            return updated

    def _drive_goal(self, goal_id: str, control: _RunControl) -> None:
        state = StateStore(self.config.database)
        try:
            while True:
                goal = state.get_goal(goal_id)
                if goal is None:
                    return
                session = state.get_session(goal["session_id"])
                if session is None:
                    raise ValueError("goal session not found")
                workspace = resolve_session_workspace(self.config.workspace, session["workspace"])
                feedback = verify(
                    workspace,
                    goal["checks"],
                    allow_commands=self.config.enable_check_commands,
                    cancellation=control.cancellation,
                )
                if control.cancellation.is_set():
                    state.update_goal(goal_id, "interrupted", feedback=feedback)
                    return
                latest_run_id = goal["runs"][-1] if goal["runs"] else None
                latest_calls = (
                    [call for call in state.list_tool_calls(goal["session_id"]) if call["run_id"] == latest_run_id]
                    if latest_run_id else []
                )
                followup_evidence_ids = ([latest_run_id] if latest_run_id else [])
                followup_evidence_ids.extend(call["tool_call_id"] for call in latest_calls[:10])
                observed_tool_names = list(dict.fromkeys(call["name"] for call in latest_calls))
                followup_action_fingerprint = _reflection_fingerprint([
                    {"name": call["name"], "arguments": call["arguments"]}
                    for call in latest_calls
                ])
                next_change = (
                    "Observed tool calls: " + ", ".join(observed_tool_names)
                    if observed_tool_names else "No tool calls were recorded in the following run."
                )
                for check_index, item in enumerate(feedback):
                    updated_reflection = state.update_goal_reflection_followup(
                        goal_id,
                        check_index,
                        bool(item["passed"]),
                        next_change=next_change,
                        evidence_ids=followup_evidence_ids[:12],
                        next_action_fingerprint=followup_action_fingerprint,
                    )
                    if updated_reflection and item["passed"]:
                        reflection = state.get_latest_goal_reflection(goal_id, check_index)
                        if reflection and reflection["following_check_passed"] is True:
                            expected = reflection["expected"]
                            check_type = expected["type"]
                            check_key = expected.get("path", expected.get("executable", ""))
                            pattern_fingerprint = goal_lesson_fingerprint(
                                check_type, check_key, reflection["next_action_fingerprint"]
                            )
                            lesson = (
                                f"Observed {check_type} check for {check_key or 'configured target'} pass "
                                f"after following action(s): {', '.join(observed_tool_names) or 'no tool calls'}."
                            )
                            state.record_goal_lesson(
                                session_id=goal["session_id"],
                                goal_id=goal_id,
                                reflection_id=reflection["id"],
                                check_type=check_type,
                                check_key=check_key,
                                pattern_fingerprint=pattern_fingerprint,
                                lesson=lesson[:512],
                                evidence_ids=reflection["evidence_ids"],
                            )
                if all(item["passed"] for item in feedback):
                    state.update_goal(goal_id, "completed", feedback=feedback)
                    return
                action_fingerprint = followup_action_fingerprint
                stop_for_repeated_failure = False
                for check_index, item in enumerate(feedback):
                    if item["passed"]:
                        continue
                    check = item["check"]
                    if check["type"] == "command":
                        expected = {
                            "type": "command",
                            "executable": Path(check["argv"][0]).name[:128],
                            "argument_count": len(check["argv"]),
                        }
                        detail = item.get("detail")
                        observed_detail = {
                            "exit_code": detail.get("exit_code"),
                            "timed_out": bool(detail.get("timed_out")),
                            "stdout_truncated": bool(detail.get("stdout_truncated")),
                            "stderr_truncated": bool(detail.get("stderr_truncated")),
                        } if isinstance(detail, dict) else "command check failed"
                    else:
                        expected = {"type": check["type"], "path": str(check["path"])[:256]}
                        if check["type"] == "file_contains":
                            expected["required_text_length"] = len(check["text"])
                        observed_detail = str(item.get("detail", ""))[:256]
                    evidence_ids = [f"goal-check:{goal_id}:{goal['iteration']}:{check_index}"]
                    if latest_run_id:
                        evidence_ids.append(latest_run_id)
                        evidence_ids.extend(call["tool_call_id"] for call in latest_calls[:10])
                    observed = {"passed": False, "detail": observed_detail}
                    reflection = state.record_goal_reflection(
                        goal_id=goal_id,
                        iteration=goal["iteration"],
                        check_index=check_index,
                        expected=expected,
                        observed=observed,
                        evidence_ids=evidence_ids[:12],
                        failure_fingerprint=_reflection_fingerprint({
                            "check_index": check_index, "expected": expected, "observed": observed,
                        }),
                        action_fingerprint=action_fingerprint,
                        repeat_threshold=self.config.goal_repeat_failure_threshold,
                    )
                    state.reject_goal_lesson_with_evidence(
                        session_id=goal["session_id"],
                        goal_id=goal_id,
                        reflection_id=reflection["id"],
                        check_type=expected["type"],
                        check_key=expected.get("path", expected.get("executable", "")),
                        evidence_ids=reflection["evidence_ids"],
                    )
                    stop_for_repeated_failure = stop_for_repeated_failure or bool(reflection["blocker"])
                if stop_for_repeated_failure:
                    state.update_goal(goal_id, "capped", feedback=feedback)
                    return
                if goal["iteration"] >= goal["max_iterations"]:
                    state.update_goal(goal_id, "capped", feedback=feedback)
                    return
                if goal["runs"]:
                    budget_summary = state.usage_summary_for_budget(goal["runs"][-1])
                else:
                    budget_summary = {"provider_calls": 0, "cost_usd": 0}
                if self.config.usage_policy.stop_reason(budget_summary):
                    state.update_goal(goal_id, "limit", feedback=feedback)
                    return

                iteration = goal["iteration"] + 1
                state.update_goal(goal_id, "running", iteration=iteration, feedback=feedback)
                run_id = state.create_run(
                    goal["session_id"],
                    agent_id=self.agent_id,
                    agent_name=self.config.model,
                    budget_group_id=goal_id,
                )
                state.link_goal_run(goal_id, run_id)
                with self._lock:
                    self._runs[run_id] = control
                message = (
                    f"Goal: {goal['objective']}\nIteration {iteration}/{goal['max_iterations']}.\n"
                    "Complete the work, but do not claim success unless the deterministic checks pass.\n"
                    "Acceptance checks and latest failures:\n"
                    + json.dumps(feedback, ensure_ascii=False)
                )
                reflections = state.list_goal_reflections(goal_id, limit=3)
                if reflections:
                    reflection_summary = [
                        {
                            "id": item["id"],
                            "trigger": item["trigger"],
                            "expected": item["expected"],
                            "observed": item["observed"],
                            "evidence_ids": item["evidence_ids"][:4],
                            "cause_hypothesis": item["cause_hypothesis"],
                            "next_change": item["next_change"],
                            "following_check_passed": item["following_check_passed"],
                            "repeat_count": item["repeat_count"],
                            "blocker": item["blocker"],
                        }
                        for item in reflections
                    ]
                    message += (
                        " Runtime reflection record (observed facts; hypotheses are not verified): "
                        + json.dumps(reflection_summary, ensure_ascii=False)
                        + " Use the evidence to change the next action; report a blocker rather than repeating an unchanged failed action."
                    )
                scoped_lessons = []
                for check in goal["checks"]:
                    if len(scoped_lessons) >= 3:
                        break
                    check_type = check["type"]
                    check_key = Path(check["argv"][0]).name[:128] if check_type == "command" else str(check["path"])[:256]
                    scoped_lessons.extend(state.list_goal_lessons(
                        goal["session_id"], check_type=check_type, check_key=check_key,
                        limit=3 - len(scoped_lessons),
                    ))
                if scoped_lessons:
                    lesson_summary = [
                        {
                            "lesson": item["lesson"],
                            "status": item["status"],
                            "support_count": item["support_count"],
                            "evidence_ids": item["evidence_ids"][-3:],
                        }
                        for item in scoped_lessons[:3]
                    ]
                    message += " Scoped lessons from this session: " + json.dumps(lesson_summary, ensure_ascii=False)
                self._execute_run(run_id, goal["session_id"], message, control)
                completed_run = state.get_run(run_id)
                if completed_run is None:
                    state.update_goal(goal_id, "error", feedback=feedback)
                    return
                if completed_run["status"] != "completed":
                    goal_status = {
                        "limit": "limit",
                        "cancelled": "interrupted",
                        "error": "error",
                    }.get(completed_run["status"], "error")
                    state.update_goal(goal_id, goal_status, feedback=feedback)
                    return
        except Exception as exc:
            goal = state.get_goal(goal_id)
            if goal is not None and goal["status"] == "running":
                state.update_goal(
                    goal_id,
                    "error",
                    feedback=[{"passed": False, "detail": f"goal controller error: {type(exc).__name__}"}],
                )
        finally:
            state.close()
            with self._lock:
                self._goals.pop(goal_id, None)

    def _register_provider(self, control: _RunControl, provider: Any) -> None:
        with self._lock:
            if not any(active is provider for active in control.providers):
                control.providers.append(provider)
            already_cancelled = control.cancellation.is_set()
        if already_cancelled:
            cancel = getattr(provider, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass

    def _execute_run(self, run_id: str, session_id: int, message: str, control: _RunControl) -> None:
        state = StateStore(self.config.database)
        is_game = False
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
            session = state.get_session(session_id)
            if session is None:
                raise ValueError("session not found")
            workspace = resolve_session_workspace(self.config.workspace, session["workspace"])
            tools = ToolRegistry(workspace, state, session_id, shell_enabled=False)
            is_game = register_game(tools, self.life)
            if is_game:
                with GameStore(self.config.database) as game:
                    with game.transient(session_id) as world:
                        world["life"].update(thinking=True,run_id=run_id,run_kind="autonomous" if message.startswith("Continue your own development in this living world.") else "human")
            delegation = DelegationManager(
                state,
                self.config.workspace,
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                provider_factory=self.provider_factory,
                usage_policy=self.config.usage_policy,
                compression_model=self.config.compression_model,
                context_limit_tokens=self.config.context_limit_tokens,
                context_max_tool_result_chars=self.config.context_max_tool_result_chars,
                max_depth=self.config.max_delegation_depth,
                max_children=self.config.max_child_agents_per_run,
                shell_enabled=False,
                repeat_failure_threshold=self.config.goal_repeat_failure_threshold,
            )
            delegation.register(tools)
            context = (GameContext if is_game else ContextBuilder)(
                state,
                max_tokens=self.config.context_limit_tokens,
                max_tool_result_chars=self.config.context_max_tool_result_chars,
                compression_provider=compression_provider,
                usage_policy=self.config.usage_policy,
            )
            agent = Agent(
                provider,
                tools,
                state,
                session_id,
                system_prompt=GAME_PROMPT if is_game else SYSTEM_PROMPT,
                usage_policy=replace(self.config.usage_policy,max_calls_per_run=game_call_cap(self.config.usage_policy.max_calls_per_run)) if is_game else self.config.usage_policy,
                context_builder=context,
                agent_id=self.agent_id,
                agent_name=self.config.model,
                entry_point="web",
                repeat_failure_threshold=self.config.goal_repeat_failure_threshold,
                runtime_context_extension=(lambda: render_game_context(state.path, session_id, workspace, self.config.model)) if is_game else None,
            )
            for _event in agent.run_turn(
                message,
                run_id=run_id,
                cancel_event=control.cancellation,
                register_provider=lambda active: self._register_provider(control, active),
            ):
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
            if is_game:
                with GameStore(self.config.database) as game:
                    try:
                        with game.transient(session_id) as world:
                            if world["life"].get("run_id")==run_id:
                                world["life"].update(thinking=False,run_id=None)
                    except ValueError:
                        pass  # Runtime closed while the cancelled turn was unwinding.
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


_EXPORT_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|authorization|cookie|credential|private[_-]?key|cvc|cvv)"
)
_EXPORT_AUTH_TEXT = re.compile(r"(?i)\b(authorization\b\s*[:=]\s*)bearer\s+[^\s,;]+")
_EXPORT_KV_TEXT = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|secret|cookie|credential)\b(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_EXPORT_TOKEN_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?s)-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----"),
)


def _redact_export(value: Any) -> Any:
    """Redact credential-shaped fields/text before returning a session download."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if isinstance(key, str) and _EXPORT_SENSITIVE_KEY.search(key)
            else _redact_export(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_export(item) for item in value]
    if isinstance(value, str):
        value = _EXPORT_AUTH_TEXT.sub(r"\1Bearer [REDACTED]", value)
        value = _EXPORT_KV_TEXT.sub(r"\1\2[REDACTED]", value)
        for pattern in _EXPORT_TOKEN_PATTERNS:
            value = pattern.sub("[REDACTED]", value)
    return value


def _game_session_export(state: StateStore, session_id: int, world: dict[str, Any]) -> dict[str, Any]:
    session = state.get_session(session_id)
    if session is None:
        raise ValueError("session not found")
    runs = state.list_runs(session_id, limit=None)
    run_exports = []
    for run in runs:
        event_rows: list[dict[str, Any]] = []
        after_id = 0
        while True:
            page = state.list_run_events(run["run_id"], after_id=after_id, limit=5000)
            if not page:
                break
            event_rows.extend(page)
            after_id = page[-1]["id"]
            if len(page) < 5000:
                break
        provider_calls = state.list_provider_calls(run["run_id"])
        run_exports.append({
            key: run.get(key) for key in
            ("run_id", "session_id", "agent_id", "parent_run_id", "depth", "agent_name", "status", "started_at", "finished_at", "error")
        } | {
            "provider_calls": [{key: call.get(key) for key in
                ("id", "model", "purpose", "usage_source", "input_tokens", "output_tokens", "cost_usd", "started_at", "finished_at")}
                for call in provider_calls],
            "events": event_rows,
        })
    payload = {
        "format": "dagi-session-export-v1",
        "exported_at": time.time(),
        "scope": {
            "includes": ["persisted visible messages", "all stored run events", "tool arguments/results/errors", "provider usage metadata", "current game world and retained history"],
            "excludes": ["raw provider request payloads/system prompts", "private internal reasoning (not stored/exportable)"],
            "history_note": "The world history is bounded by the runtime; all remaining persisted entries and all run/tool events are included.",
            "redaction_note": "Credential-shaped keys and common bearer/API-token patterns are redacted; review before sharing externally.",
        },
        "session": {key: session.get(key) for key in ("id", "title", "created_at", "parent_id")},
        "messages": state.messages(session_id, include_metadata=True),
        "runs": run_exports,
        "tool_calls": state.list_tool_calls(session_id),
        "game_world": world,
    }
    return _redact_export(payload)


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
