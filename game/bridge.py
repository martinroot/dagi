"""Small adapter to the existing web worker, agent loop and durable tool events."""
from __future__ import annotations

import json
from pathlib import Path

from dagi_core.agent import SYSTEM_PROMPT
from dagi_core.tools import Tool, ToolResult

from .store import GameStore
from .world import act, evolve, keys, observation, reflect, set_goal

SOURCE_FILES = {
    "game/world.py": Path(__file__).with_name("world.py"),
    "game/store.py": Path(__file__).with_name("store.py"),
    "game/bridge.py": Path(__file__),
    "game/static/game.js": Path(__file__).parent / "static" / "game.js",
    "game/static/index.html": Path(__file__).parent / "static" / "index.html",
    "dagi_core/agent.py": Path(__file__).parent.parent / "dagi_core" / "agent.py",
    "dagi_core/web.py": Path(__file__).parent.parent / "dagi_core" / "web.py",
}

GAME_PROMPT = SYSTEM_PROMPT + """

You are embodied in the Dagi game debugging sandbox. Your stickman IS your body in
this session, not another NPC. The application supplies identity via game_inspect.
Inspect before acting: know your session, body, workspace, source code and UI.
A human watches your actual server-produced pose in a browser canvas and reads
your streamed chat and tool outcomes. You do not have visual pixel perception;
game_inspect supplies structured scene observations matching what is rendered.
Do not pretend to see screenshots or claim subjective consciousness.

Use the existing user goal and chat to build a bounded sequence of experiments:
observe -> state a short intended action -> act -> inspect measured effects ->
record a brief operational reflection when useful -> change the next experiment.
Use game_goal for an explicit reach-x check derived from the user's request.
Changing a goal or world to make a check easier does not prove the original task.
A successful action/configuration save does not mean the goal passed. Hypotheses
are not verified lessons. Do not report a fall, walk, jump or obstacle clearance
unless observations support it. Physics advances only by game_act; model latency
and opening the browser do not advance the world. Each turn has bounded tool rounds.

game_evolve changes physical objects, posture/movement parameters and named,
bounded action programs. This is your editable behavior code, persisted per
session. The Python engine is application code: inspect its actual source with
game_inspect(source). File tools write only your session workspace for experiments,
notes and proposed code extensions. Writing a file does not hot-load it into the
engine. Never claim that an unexecuted code proposal changed the running body.
Only your own world is available. Delegated agents do not inherit your body.
"""


def identity(session_id, workspace):
    return {
        "session_id": session_id, "body_id": f"stickman:{session_id}",
        "role": "embodied agent; one body per game session",
        "workspace": str(workspace),
        "code": {"engine": "game/world.py", "behavior": "world.controller + world.behaviors (editable with game_evolve)",
                 "adapter": "game/bridge.py", "agent_loop": "dagi_core/agent.py", "viewer": "game/static/game.js",
                 "source_files": sorted(SOURCE_FILES)},
        "interface": {"surface": "browser canvas + streamed chat + tool trace + scene inspector",
                      "human_observer": True, "perception": "structured scene state; no screenshot input",
                      "time": "only advances on game_act", "coordinates": "1000x600; x right; y down; floor y=540",
                      "visibility": "canvas shows joints, links, obstacles, target; chat shows public answers and tool evidence"},
    }


def compact_scene(world):
    """Keep normal motor feedback small; detailed state stays available on demand."""
    return compact_observation(observation(world))


def compact_observation(scene):
    scene["object_count"] = len(scene.pop("objects"))
    scene["behavior_names"] = list(scene.pop("behaviors"))
    latest = scene.get("latest_reflection")
    if latest:
        scene["latest_reflection"] = {name: latest[name] for name in
            ("expected", "hypothesis", "next_test", "evidence_revision", "evidence_tick", "status")}
    return scene


def register_game(tools):
    """Return whether this is a game session; ordinary sessions get no game tools."""
    with GameStore(tools.state.path) as store:
        if store.get(tools.session_id) is None:
            return False
    tools.memory_session_scope = True

    def inspect(args):
        keys(args, ("view", "path", "offset", "limit"))
        view = args.get("view", "state")
        if view == "source":
            path = args.get("path")
            if not isinstance(path, str) or path not in SOURCE_FILES:
                raise ValueError("path must be one of the source_files returned by game_inspect")
            offset, limit = args.get("offset", 0), args.get("limit", 6000)
            if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 6000:
                raise ValueError("offset must be a nonnegative integer; limit must be 1..6000")
            source = SOURCE_FILES[path].read_text(encoding="utf-8")
            return {"path": path, "offset": offset, "source": source[offset:offset + limit],
                    "next_offset": offset + limit if offset + limit < len(source) else None,
                    "authority": "installed application source; read-only through this tool"}
        with GameStore(tools.state.path) as store:
            world = store.get(tools.session_id)
        if view in ("objects", "behaviors"):
            offset = args.get("offset", 0)
            if type(offset) is not int or offset < 0:
                raise ValueError("offset must be a nonnegative integer")
            items = world["objects"] if view == "objects" else [{"name": name, "steps": steps} for name, steps in world["behaviors"].items()]
            limit = 8 if view == "objects" else 2
            return {"revision": world["revision"], "items": items[offset:offset + limit], "total": len(items),
                    "next_offset": offset + limit if offset + limit < len(items) else None}
        if view != "state":
            raise ValueError("view must be state, objects, behaviors, or source")
        return {"self": identity(tools.session_id, tools.workspace), "scene": compact_scene(world),
                "joints": {name: [round(p["x"], 2), round(p["y"], 2)] for name, p in world["nodes"].items()}}

    def mutate(operation, args, context):
        with GameStore(tools.state.path) as store:
            kwargs = {"cancelled": context.cancel_event.is_set} if operation is act and context.cancel_event else {}
            return compact_observation(store.apply(tools.session_id, operation, args, **kwargs))

    def wrap(handler):
        def call(args, context):
            try:
                result = handler(args, context)
            except ValueError as exc:
                return ToolResult(json.dumps({"error": str(exc), "world_changed": False}), is_error=True)
            return ToolResult(json.dumps(result, ensure_ascii=False), presentation={
                "type": "game.observation", "summary": "Embodied sandbox observation",
                "diagnostics": {"session_id": tools.session_id, "body_id": f"stickman:{tools.session_id}"},
            })
        return call

    specs = [
        ("game_inspect", "Observe your identity, body, physics, measured pose, goals and viewer. view=objects or behaviors returns paged details (use next_offset). Read actual installed code with view=source and an allowlisted path.",
         {"view": {"type": "string", "enum": ["state", "objects", "behaviors", "source"]}, "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, [], lambda a, c: inspect(a), True),
        ("game_act", "Advance your actual physical body. For left/right/idle/jump, provide frames and omit name. For behavior, provide only name; saved steps define duration. A bounded frames hint on behavior and an empty name on a simple action are ignored and reported. Returns measured effects; a tool success is not a goal success.",
         {"action": {"type": "string", "enum": ["left", "right", "idle", "jump", "behavior"]}, "frames": {"type": "integer", "minimum": 1, "maximum": 240, "description": "Used for simple actions; ignored for behavior."}, "name": {"type": "string", "description": "Required for behavior; omit or leave empty for simple actions."}}, ["action"], lambda a, c: mutate(act, a, c), False),
        ("game_evolve", "Change your own world/behavior. operation=add uses object {id,kind:block|marker,x,y,width,height,label}; remove uses id; controller uses values {speed:0..180,balance:0..1,stride:0..24,jump:0..450}; physics uses values {gravity:100..1600}; behavior uses name,steps:[{action,frames}] (<=8 steps, <=960 frames). Configuration success requires a subsequent physical test.",
         {"operation": {"type": "string", "enum": ["add", "remove", "controller", "physics", "behavior"]}, "object": {"type": "object"}, "id": {"type": "string"}, "values": {"type": "object"}, "name": {"type": "string"}, "steps": {"type": "array", "items": {"type": "object"}}}, ["operation"], lambda a, c: mutate(evolve, a, c), False),
        ("game_goal", "Configure a reach-x check from the human request: upright and grounded within tolerance of x. This check verifies only that pose; it is distinct from completing the user's overall task.",
         {"x": {"type": "number"}, "tolerance": {"type": "number"}, "label": {"type": "string"}}, ["x"], lambda a, c: mutate(set_goal, a, c), False),
        ("game_reflect", "Save a short operational experiment note: expected, hypothesis, next_test. Observed state and evidence revision are attached by the runtime. A note is a hypothesis, not verified learning.",
         {name: {"type": "string"} for name in ("expected", "hypothesis", "next_test")}, ["expected", "hypothesis", "next_test"], lambda a, c: mutate(reflect, a, c), False),
    ]
    for name, description, properties, required, handler, retryable in specs:
        tools.register(Tool(name, description, {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                            wrap(handler), retryable=retryable, context_aware=True))
    return True
