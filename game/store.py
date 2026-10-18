"""Session-scoped world snapshots, serialized mutations and replay frames in SQLite."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from .world import fresh_world, observation, upgrade


class GameStore:
    def __init__(self, database):
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
        self.db.execute("INSERT INTO game_worlds VALUES (?, ?)", (session_id, json.dumps(world)))
        self.db.commit()
        return world

    def get(self, session_id):
        row = self.db.execute("SELECT world_json FROM game_worlds WHERE session_id=?", (session_id,)).fetchone()
        return upgrade(json.loads(row[0])) if row else None

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
