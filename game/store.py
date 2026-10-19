"""Session-scoped world snapshots, serialized mutations and replay frames in SQLite."""
from __future__ import annotations

import json
import hashlib
import sqlite3
import copy
import time
from pathlib import Path
from threading import RLock
from contextlib import contextmanager

from .world import fresh_world, observation, upgrade

_LIVE = {}
_DATABASES = set()
_GUARD = RLock()


class LiveSlot:
    def __init__(self, world):
        self.lock = RLock()
        self.world = world
        self.simulator = None
        self.vision = None
        self.saved_at = time.monotonic()


def enable_live(database):
    with _GUARD:
        _DATABASES.add(str(Path(database).resolve()))


def disable_live(database):
    key = str(Path(database).resolve())
    with _GUARD:
        for item in [k for k in _LIVE if k[0] == key]:
            del _LIVE[item]
        _DATABASES.discard(key)


def live_slot(database, session_id):
    return _LIVE.get((str(Path(database).resolve()), session_id))


def clock_tick(database, session_id):
    """No SQLite, connection setup, JSON serialization or provider on this path."""
    slot = live_slot(database, session_id)
    if slot is None:
        return
    from .living import advance
    from .rigid import RigidSimulator
    with slot.lock:
        world = slot.world
        if not world["life"]["running"]:
            return
        if slot.simulator is None and world.get("physics_engine") == "chipmunk":
            slot.simulator = RigidSimulator(world)
        try:
            advance(world, 1, simulator=slot.simulator, diagnostics=False)
            world["revision"] += 1
        except (ValueError, KeyError) as exc:
            world["policy_error"] = str(exc)[:240]
            world["failed_policy"] = world["active_policy"]
            if world.get("active_project"):
                world["project_error"]={"name":world["active_project"],"detail":str(exc)[:240]}
                world["active_project"]=None
                world["direction"]={}
            world["active_policy"] = None
            world["life"]["error"] = str(exc)[:240]
            world["life"]["intent"] = "Контроллер отключён после ошибки; сохраняю устойчивость"
            world["revision"] += 1


class GameStore:
    def __init__(self, database):
        self.key = str(Path(database).resolve())
        self.db = sqlite3.connect(database, timeout=10)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS game_worlds (
            session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            world_json TEXT NOT NULL
        )""")
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def create(self, session_id):
        world = fresh_world(session_id)
        world["project_scope"]=hashlib.sha256(f"{self.key}:{session_id}".encode()).hexdigest()
        if self.key in _DATABASES:
            world["physics_engine"] = "chipmunk"
        self.db.execute("INSERT INTO game_worlds VALUES (?, ?)", (session_id, json.dumps(world)))
        self.db.commit()
        if self.key in _DATABASES:
            with _GUARD:
                _LIVE[(self.key, session_id)] = LiveSlot(world)
        return world

    def get(self, session_id):
        slot = _LIVE.get((self.key, session_id))
        if slot:
            with slot.lock:
                return copy.deepcopy(slot.world)
        row = self.db.execute("SELECT world_json FROM game_worlds WHERE session_id=?", (session_id,)).fetchone()
        world = upgrade(json.loads(row[0])) if row else None
        if world and not world.get("project_scope"):
            world["project_scope"]=hashlib.sha256(f"{self.key}:{session_id}".encode()).hexdigest()
        if world and self.key in _DATABASES:
            with _GUARD:
                _LIVE.setdefault((self.key, session_id), LiveSlot(copy.deepcopy(world)))
        return world

    def checkpoint(self, session_id):
        slot = _LIVE.get((self.key, session_id))
        if slot:
            with slot.lock:
                payload = json.dumps(slot.world, allow_nan=False, separators=(",", ":"))
                self.db.execute("UPDATE game_worlds SET world_json=? WHERE session_id=?", (payload, session_id))
                self.db.commit()
                slot.saved_at = time.monotonic()

    @contextmanager
    def transient(self,session_id):
        self.get(session_id)
        slot=_LIVE.get((self.key,session_id))
        if slot is None:
            raise ValueError("live game session not found")
        with slot.lock:
            yield slot.world
            slot.world["revision"]+=1

    def recover_releases(self):
        """A crash before activation leaves the live world unchanged, never auto-replay."""
        for (session_id,) in self.db.execute("SELECT session_id FROM game_worlds").fetchall():
            current = self.get(session_id)
            if current["draft"] and current["draft"]["state"] == "scheduled":
                with self.mutation(session_id) as world:
                    world["draft"]["state"] = "tested"
                    world["draft"]["release_error"] = "Activation interrupted; live world unchanged. Inspect before retry."

    def list_sessions(self):
        return [{"id": row[0], "title": row[1]} for row in self.db.execute(
            "SELECT s.id, s.title FROM sessions s JOIN game_worlds g ON g.session_id=s.id ORDER BY s.id DESC LIMIT 100"
        )]

    @contextmanager
    def mutation(self, session_id):
        if self.key in _DATABASES:
            self.get(session_id)  # Load exactly once; authoritative state then stays in memory.
            slot = _LIVE.get((self.key, session_id))
            if slot is None:
                raise ValueError("game session not found")
            with slot.lock:
                world = copy.deepcopy(slot.world)
                yield world
                world["revision"] += 1
                # Durable semantic mutations commit before becoming visible.
                self.db.execute("UPDATE game_worlds SET world_json=? WHERE session_id=?", (
                    json.dumps(world, allow_nan=False, separators=(",", ":")), session_id))
                self.db.commit()
                old = slot.world
                if old["nodes"] != world["nodes"] or old["objects"] != world["objects"] or old["material"] != world["material"] or old.get("mechanisms")!=world.get("mechanisms") or old.get("appendages")!=world.get("appendages"):
                    slot.simulator = None
                elif slot.simulator:
                    slot.simulator.world = world
                slot.world = world
            return
        # One transaction per bounded action. A second writer cannot overwrite stale state.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            world = self.get(session_id)
            if world is None:
                raise ValueError("game session not found")
            yield world
            world["revision"] += 1
            self.db.execute("UPDATE game_worlds SET world_json=? WHERE session_id=?", (
                json.dumps(world, allow_nan=False, separators=(",", ":")), session_id,
            ))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def apply(self, session_id, operation, args, **kwargs):
        with self.mutation(session_id) as world:
            result = operation(world, args, **kwargs)
            result["revision"] = world["revision"] + 1
            if result["kind"] != "renderer_report":
                world["history"] = (world["history"] + [result])[-40:]
        return observation(world)
