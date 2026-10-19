"""One server clock for opt-in living worlds and bounded independent model turns."""
from __future__ import annotations

import json
import time
from threading import Event, Lock, Thread

from .turns import game_call_cap
from .living import advance
from .store import GameStore, clock_tick, enable_live, disable_live, live_slot
from .world import keys, observation


ITERATION_PROMPT = """Continue your own development in this living world.
Choose the next useful experiment yourself, guided by the human's latest request
and actual observations. Keep a coherent activity; you may improve body control,
physical interaction, appearance, a useful invented instrument or world mechanics.
Write and test a coherent JavaScript project coordinating physical feedback, camera, expression and invented graphics. Use real sensors for outcomes.
If a previous draft exists, inspect and repair or discard it before beginning another.
Check the previous outcome, fix actual errors, and publish one coherent change if
evidence supports it. A failed attempt is useful evidence; no fake success score.
Do not stop at a plan or apology when a concrete repair is possible. Preserve the
human's controls. Leave an active project or policy that continues locally between turns.
"""


class LifeRuntime:
    def __init__(self, app):
        self.app = app
        self._stop = Event()
        self._lock = Lock()
        self._active = set()
        self._next_thought = {}
        self._pending = {}
        self._thread = None
        self._clock_thread = None

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._clock_thread:
            self._clock_thread.join(timeout=3)
        with self._lock:
            active = list(self._active)
        for session_id in active:
            with GameStore(self.app.config.database) as store:
                with store.mutation(session_id) as world:
                    world["life"].update(running=False, thinking=False, status="paused", run_id=None)

        disable_live(self.app.config.database)

    def recover(self):
        enable_live(self.app.config.database)
        # Never automatically spend API budget or replay elapsed time on restart.
        with GameStore(self.app.config.database) as store:
            for (session_id,) in store.db.execute("SELECT session_id FROM game_worlds").fetchall():
                world = store.get(session_id)
                if world["life"]["running"] or world["life"]["thinking"] or world.get("physics_engine")!="chipmunk":
                    with store.mutation(session_id) as world:
                        world["physics_engine"] = "chipmunk"
                        world["life"].update(running=False, thinking=False, status="paused", run_id=None,
                                             error="Server restarted; resume explicitly. Programs and memory preserved.")

    def control(self, session_id, args):
        cancel_control=None
        keys(args, ("action", "iterations", "name"))
        action = args.get("action")
        if action not in {"start", "play", "pause", "select"}:
            raise ValueError("life action must be start, play, pause or select")
        iterations = args.get("iterations", 5)
        if type(iterations) is not int or not 1 <= iterations <= 20:
            raise ValueError("iterations must be an integer in 1..20")
        with self._lock:
            with GameStore(self.app.config.database) as store:
                with store.mutation(session_id) as world:
                    life = world["life"]
                    if action == "select":
                        if world["draft"]:
                            raise ValueError("finish or discard the draft before selecting a program")
                        if args.get("name") not in world["policies"] and args.get("name") not in world["projects"]:
                            raise ValueError("unknown feedback policy")
                        if args["name"] in world["projects"]:
                            world.update(active_project=args["name"],active_policy=None,project_state={},project_started=world["tick"],project_error=None)
                        else:
                            world.update(active_policy=args["name"],active_project=None)
                        world["direction"]={};world["event_queue"]=[]
                        world["policy_state"] = {}
                        world["policy_error"] = None
                    elif action == "pause":
                        life.update(running=False, thinking=False, status="paused", run_id=None)
                        life["pause_epoch"]=life.get("pause_epoch",0)+1
                        self._active.discard(session_id)
                        owned = self._pending.pop(session_id,None)
                        if owned:
                            with self.app._lock:
                                control = self.app._runs.get(owned)
                            if control:
                                cancel_control=control
                    elif action in {"start", "play"}:
                        if session_id in self._pending:
                            raise ValueError("wait for the current iteration to finish before restarting")
                        if action == "play" and not (world["active_policy"] or world["active_project"]):
                            raise ValueError("no feedback policy saved yet; start development or ask the agent to create one")
                        life.update(running=True, error=None, status="observing", thinking=False,
                                    iteration=0, limit=iterations if action == "start" else 0, run_id=None)
                        self._active.add(session_id)
                        self._next_thought[session_id] = 0
                    result = dict(life)
            self._start_threads()
        if cancel_control is not None:
            self.app._cancel_control(cancel_control)
        return {"life": result, "max_provider_calls_per_iteration": game_call_cap(self.app.config.usage_policy.max_calls_per_run),
                "scope": "Start authorizes bounded model turns; play uses no model calls. Pause cancels the owned turn. No auto-resume after server restart."}

    def _start_threads(self):
        if self._thread is None:
            self._thread = Thread(target=self._loop, name="dagi-brain-scheduler", daemon=True)
            self._clock_thread = Thread(target=self._physics_loop, name="dagi-physics-60hz", daemon=True)
            self._thread.start()
            self._clock_thread.start()

    def ensure_clock(self, session_id, expected_pause=None):
        with self._lock:
            slot=live_slot(self.app.config.database,session_id)
            if expected_pause is not None and slot and slot.world["life"].get("pause_epoch",0)!=expected_pause:
                return
            if session_id in self._active and slot and slot.world["life"]["running"]:
                return
            with GameStore(self.app.config.database) as store:
                with store.mutation(session_id) as world:
                    world["life"]["running"] = True
                    world["life"]["limit"] = 0  # Motor execution never authorizes new paid model turns.
                    world["life"]["iteration"] = 0
                    world["life"]["error"] = None
                    world["life"]["status"] = "observing"
            self._active.add(session_id)
            self._start_threads()

    def _physics_loop(self):
        deadline = time.perf_counter()
        while not self._stop.is_set():
            deadline += 1 / 60
            with self._lock:
                sessions = tuple(self._active)
            for session_id in sessions:
                try:
                    clock_tick(self.app.config.database, session_id)
                except Exception:
                    # An engine error affects this world, never every other session.
                    slot = live_slot(self.app.config.database, session_id)
                    if slot:
                        with slot.lock:
                            slot.world["policy_error"] = "Physical runtime failed; inspect and repair the current policy."
            delay = deadline - time.perf_counter()
            if delay < -.05:
                deadline = time.perf_counter()  # Bound recovery; never fast-forward seconds of unseen motion.
            self._stop.wait(max(0, delay))

    def _loop(self):
        while not self._stop.wait(.1):
            with self._lock:
                active = list(self._active)
            for session_id in active:
                try:
                    self.step(session_id)
                except Exception as exc:
                    with GameStore(self.app.config.database) as store:
                        with store.mutation(session_id) as world:
                            world["life"].update(running=False, thinking=False, status="error",
                                                 error=f"{type(exc).__name__}: {str(exc)[:200]}")
                    with self._lock:
                        self._active.discard(session_id)

    def step(self, session_id):
        with GameStore(self.app.config.database) as store:
            world = store.get(session_id)
            if not world or not world["life"]["running"]:
                return
            slot = live_slot(self.app.config.database, session_id)
            if slot and time.monotonic() - slot.saved_at > 2:
                store.checkpoint(session_id)
            world = store.get(session_id)
            life = world["life"]
            pending = self._pending.get(session_id)
            with self.app._lock:
                still_running = pending in self.app._runs if pending else False
                busy = self.app._session_busy(session_id)
            if pending and not still_running:
                with self.app_state() as state:
                    run = state.get_run(pending)
                with store.mutation(session_id) as current:
                    current["life"].update(thinking=False, status="observing", run_id=None)
                    if run and run["status"] != "completed":
                        current["life"]["error"] = f"Итерация завершена со статусом {run['status']}. Подробности — в чате."
                self._pending.pop(session_id, None)
                self._next_thought[session_id] = time.monotonic() + 4
                return
            if busy or life["iteration"] >= life["limit"] or time.monotonic() < self._next_thought.get(session_id, 0):
                return
            # Serialize starting a brain turn with pause/start requests. A paused
            # world can never launch a late turn after its control response.
            with self._lock:
                world = store.get(session_id)
                if not world["life"]["running"] or session_id not in self._active:
                    return
                data = {"iteration": life["iteration"] + 1, "limit": life["limit"],
                        "world_version": world["version"], "active_policy": world["active_policy"], "active_project":world["active_project"], "project_error":world["project_error"],
                        "position": observation(world)["position"], "error": world["policy_error"],
                        "last_change": world["evolution"][-1]["objective"] if world["evolution"] else None}
                try:
                    started = self.app.start_run(session_id, ITERATION_PROMPT + "\nCurrent evidence (data):\n" + json.dumps(data, ensure_ascii=False))
                except RuntimeError:
                    return  # A human run won the race; try after it completes.
                self._pending[session_id] = started["run_id"]
                with store.mutation(session_id) as current:
                    current["life"].update(thinking=True, status="developing", iteration=life["iteration"] + 1,
                                            run_id=started["run_id"])

    def app_state(self):
        # Local context adapter avoids importing WebApp (and a circular import).
        from contextlib import closing
        from dagi_core.state import StateStore
        return closing(StateStore(self.app.config.database))
