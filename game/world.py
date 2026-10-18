"""Deterministic position-based ragdoll physics and a bounded world-edit language.

The posture motor is an explicit assist, not a claim of biomechanical simulation.
Time advances only through actions, independent of viewers, network or model latency.
"""
from __future__ import annotations

import copy
import math

DT = 1 / 60
FLOOR = 540
WIDTH = 1000
OFFSETS = {
    "head": (0, -78), "neck": (0, -58), "hip": (0, 0),
    "left_elbow": (-22, -40), "left_hand": (-30, -14),
    "right_elbow": (22, -40), "right_hand": (30, -14),
    "left_knee": (-12, 42), "left_foot": (-18, 84),
    "right_knee": (12, 42), "right_foot": (18, 84),
}
PAIRS = [
    ("head", "neck"), ("neck", "hip"),
    ("neck", "left_elbow"), ("left_elbow", "left_hand"),
    ("neck", "right_elbow"), ("right_elbow", "right_hand"),
    ("hip", "left_knee"), ("left_knee", "left_foot"),
    ("hip", "right_knee"), ("right_knee", "right_foot"),
]
LINKS = [(a, b, math.dist(OFFSETS[a], OFFSETS[b])) for a, b in PAIRS]


def number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number in {low}..{high}")
    return value


def text(value, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty text, at most {limit} characters")
    return value


def keys(args, allowed):
    if not isinstance(args, dict) or set(args) - set(allowed):
        raise ValueError(f"expected an object with only these fields: {', '.join(allowed)}")


def fresh_world(session_id):
    return {
        "schema_version": 2, "session_id": session_id, "body_id": f"stickman:{session_id}",
        "revision": 0, "tick": 0, "gravity": 900,
        "nodes": {name: {"x": 180.0 + x, "y": 450.0 + y, "px": 180.0 + x, "py": 450.0 + y} for name, (x, y) in OFFSETS.items()},
        "controller": {"speed": 95, "balance": 0.85, "stride": 12, "jump": 310},
        "objects": [], "behaviors": {}, "goal": None, "reflections": [], "history": [], "motion": [],
        "widgets": [], "components": [], "theme": {"background": "#ffffff", "accent": "#e6703a"},
        "version": 0, "draft": None, "last_release": None, "previous": None, "browser_report": None,
    }


def upgrade(world):
    """Additive migration of v1 saved worlds; reading never resets a learned body."""
    for name, value in {"widgets": [], "components": [], "theme": {"background": "#ffffff", "accent": "#e6703a"},
                        "version": 0, "draft": None, "last_release": None, "previous": None, "browser_report": None}.items():
        world.setdefault(name, copy.deepcopy(value))
    world["schema_version"] = 2
    return world


def frame(world):
    return {"tick": world["tick"], "nodes": {name: [round(p["x"], 2), round(p["y"], 2)] for name, p in world["nodes"].items()}}


def observation(world):
    nodes = world["nodes"]
    hip, head = nodes["hip"], nodes["head"]
    grounded = any(_on_surface(world, nodes[name], 7) for name in ("left_foot", "right_foot"))
    upright = head["y"] < hip["y"] - 45 and abs(head["x"] - hip["x"]) < 35
    goal = copy.deepcopy(world["goal"])
    if goal:
        distance = abs(hip["x"] - goal["x"])
        goal.update({"distance": round(distance, 2), "passed": distance <= goal["tolerance"] and upright and grounded,
                     "scope": "Current pose reaches configured x while upright and grounded; does not verify the whole user task."})
    return {
        "session_id": world["session_id"], "body_id": world["body_id"], "revision": world["revision"],
        "tick": world["tick"], "seconds": round(world["tick"] * DT, 2),
        "position": {"x": round(hip["x"], 2), "y": round(hip["y"], 2)},
        "upright": upright, "grounded": grounded,
        "physics": {"gravity": world["gravity"], "step_hz": 60, "floor_y": FLOOR, "width": WIDTH,
                    "clock": "action-driven", "solver": "Verlet + distance constraints + circle/AABB contacts; assisted posture motor"},
        "controller": copy.deepcopy(world["controller"]), "objects": copy.deepcopy(world["objects"]),
        "behaviors": copy.deepcopy(world["behaviors"]), "goal": goal,
        "last_action": copy.deepcopy(world["history"][-1]) if world["history"] else None,
        "latest_reflection": copy.deepcopy(world["reflections"][-1]) if world["reflections"] else None,
        "version": world.get("version", 0), "widget_count": len(world.get("widgets", [])),
    }


def _on_surface(world, p, tolerance):
    radius = 4
    if abs(p["y"] + radius - FLOOR) <= tolerance:
        return True
    return any(o["kind"] == "block" and o["x"] - radius <= p["x"] <= o["x"] + o["width"] + radius
               and abs(p["y"] + radius - o["y"]) <= tolerance for o in world["objects"])


def _collide(world, p, radius):
    p["x"] = max(radius, min(WIDTH - radius, p["x"]))
    p["y"] = max(radius, min(FLOOR - radius, p["y"]))
    for o in world["objects"]:
        if o["kind"] != "block":
            continue
        # Expanded AABB contact for circular joints; no rigid-segment collision.
        left, right = o["x"] - radius, o["x"] + o["width"] + radius
        top, bottom = o["y"] - radius, o["y"] + o["height"] + radius
        if left < p["x"] < right and top < p["y"] < bottom:
            choices = [(p["x"] - left, "x", left), (right - p["x"], "x", right),
                       (p["y"] - top, "y", top), (bottom - p["y"], "y", bottom)]
            _, axis, value = min(choices)
            p[axis] = value


def _step(world, direction, climbing=0):
    nodes, motor = world["nodes"], world["controller"]
    grounded = any(_on_surface(world, nodes[n], 9) for n in ("left_foot", "right_foot"))
    hip = nodes["hip"]
    base_x, base_y = hip["x"], hip["y"]
    phase = world["tick"] * DT * 9
    for name, p in nodes.items():
        vx, vy = (p["x"] - p["px"]) * 0.985, (p["y"] - p["py"]) * 0.995
        # Velocity steering is bounded and weaker in the air.
        vx += (direction * motor["speed"] * DT - vx) * (0.12 if grounded else 0.02)
        p["px"], p["py"] = p["x"], p["y"]
        p["x"] += vx
        p["y"] += vy + world["gravity"] * DT * DT
        for obj in world["objects"]:
            if obj["kind"] == "fan" and obj["enabled"]:
                dx, dy = p["x"] - obj["x"], p["y"] - obj["y"]
                if math.hypot(dx, dy) < obj["range"]:
                    scale = (1 - math.hypot(dx, dy) / obj["range"]) * obj["force"] * DT * DT
                    angle = math.radians(obj["angle"])
                    p["x"] += math.cos(angle) * scale
                    p["y"] += math.sin(angle) * scale
        if motor["balance"]:
            ox, oy = OFFSETS[name]
            if "foot" in name or "knee" in name:
                swing = math.sin(phase + (math.pi if name.startswith("right") else 0)) * abs(direction)
                ox += swing * motor["stride"]
                if "foot" in name:
                    oy -= max(0, swing) * 9
            strength = motor["balance"] * 0.08
            p["x"] += (base_x + ox - p["x"]) * strength
            p["y"] += (base_y + oy - p["y"]) * strength
    if climbing:
        ladder = next((o for o in world["objects"] if o["kind"] == "ladder"
                       and abs(hip["x"] - o["x"]) <= o["width"] / 2 + 30
                       and o["y"] - 10 <= hip["y"] <= o["y"] + o["height"] + 10), None)
        if ladder:
            for p in nodes.values():
                p["y"] += climbing * motor["speed"] * DT - (p["y"] - p["py"]) * 0.9
    # Assisted stance reacts to actual nearby support; no support -> no levitation.
    supports = [FLOOR] + [o["y"] for o in world["objects"] if o["kind"] == "block"
                          and o["x"] <= hip["x"] <= o["x"] + o["width"] and o["y"] >= hip["y"]]
    support = min(supports)
    lift = max(0, hip["y"] - (support - 88)) * motor["balance"] * 0.18 if grounded else 0
    for p in nodes.values():
        p["y"] -= min(lift, 5)
    for _ in range(10):
        for a, b, length in LINKS:
            p, q = nodes[a], nodes[b]
            dx, dy = q["x"] - p["x"], q["y"] - p["y"]
            distance = max(0.0001, math.hypot(dx, dy))
            correction = (distance - length) / distance * 0.5
            p["x"] += dx * correction
            p["y"] += dy * correction
            q["x"] -= dx * correction
            q["y"] -= dy * correction
        for name, p in nodes.items():
            _collide(world, p, 12 if name == "head" else 4)
    world["tick"] += 1


def validate_action(args):
    keys(args, ("action", "frames", "name"))
    action = args.get("action")
    if not isinstance(action, str) or action not in {"left", "right", "idle", "jump", "climb_up", "climb_down", "behavior"}:
        raise ValueError("action must be left, right, idle, jump, climb_up, climb_down, or behavior")
    ignored = []
    if action == "behavior":
        text(args.get("name"), 40, "name")
        if "frames" in args:
            frames_hint = args["frames"]
            number(frames_hint, 1, 240, "frames")
            if not isinstance(frames_hint, int):
                raise ValueError("frames must be an integer")
            ignored.append("frames")
        return action, None, ignored
    if "name" in args:
        if args["name"] != "":
            raise ValueError("name is only valid for action=behavior")
        ignored.append("name")
    frames = args.get("frames", 60)
    number(frames, 1, 240, "frames")
    if not isinstance(frames, int):
        raise ValueError("frames must be an integer")
    return action, frames, ignored


def act(world, args, cancelled=lambda: False):
    action, frames, ignored = validate_action(args)
    is_behavior = action == "behavior"
    command = {key: copy.deepcopy(value) for key, value in args.items() if key not in ignored}
    before = observation(world)
    if action == "behavior":
        steps = world["behaviors"].get(args["name"])
        if steps is None:
            raise ValueError("unknown behavior")
    else:
        steps = [{"action": action, "frames": frames}]
    motion = [frame(world)]
    for step in steps:
        action, frames, _ignored = validate_action(step)
        if action == "jump" and observation(world)["grounded"]:
            for p in world["nodes"].values():
                p["py"] = p["y"] + world["controller"]["jump"] * DT
        for i in range(frames):
            if cancelled():
                raise ValueError("action cancelled before world commit")
            _step(world, -1 if action == "left" else 1 if action == "right" else 0,
                  -1 if action == "climb_up" else 1 if action == "climb_down" else 0)
            if i % 8 == 0:
                motion.append(frame(world))
    motion.append(frame(world))
    world["motion"] = motion[-122:]
    after = observation(world)
    return {"kind": "action", "command": command, "ignored_arguments": ignored,
            "duration_source": "saved behavior steps" if is_behavior else "frames",
            "from_tick": before["tick"], "to_tick": after["tick"],
            "displacement_x": round(after["position"]["x"] - before["position"]["x"], 2),
            "upright": after["upright"], "grounded": after["grounded"], "goal": after["goal"]}


def evolve(world, args):
    keys(args, ("operation", "object", "id", "values", "name", "steps"))
    operation = args.get("operation")
    if not isinstance(operation, str):
        raise ValueError("operation must be text")
    operation_fields = {"add": ("object",), "remove": ("id",), "controller": ("values",),
                        "physics": ("values",), "behavior": ("name", "steps")}
    if operation in operation_fields:
        keys(args, ("operation", *operation_fields[operation]))
    if operation == "add":
        if len(world["objects"]) >= 32:
            raise ValueError("world is limited to 32 objects")
        obj = copy.deepcopy(args.get("object"))
        keys(obj, ("id", "kind", "x", "y", "width", "height", "label", "force", "range", "angle", "enabled"))
        text(obj.get("id"), 40, "object id")
        if any(o["id"] == obj["id"] for o in world["objects"]):
            raise ValueError("object id already exists")
        if not isinstance(obj.get("kind"), str) or obj["kind"] not in {"block", "marker", "ladder", "fan"}:
            raise ValueError("object kind must be block, marker, ladder, or fan")
        number(obj.get("x"), 0, WIDTH, "x")
        number(obj.get("y"), 0, FLOOR, "y")
        if "label" in obj:
            text(obj["label"], 80, "label")
        if obj["kind"] == "block":
            keys(obj, ("id", "kind", "x", "y", "width", "height", "label"))
            number(obj.get("width"), 10, 400, "width")
            number(obj.get("height"), 10, 300, "height")
            if obj["x"] + obj["width"] > WIDTH or obj["y"] + obj["height"] > FLOOR:
                raise ValueError("block must fit inside world bounds")
            # Prevent a world edit from embedding the agent or teleporting it on contact.
            if any(obj["x"] - 14 < p["x"] < obj["x"] + obj["width"] + 14
                   and obj["y"] - 14 < p["y"] < obj["y"] + obj["height"] + 14 for p in world["nodes"].values()):
                raise ValueError("block overlaps the body; place it elsewhere")
        elif obj["kind"] == "ladder":
            keys(obj, ("id", "kind", "x", "y", "width", "height", "label"))
            number(obj.get("width"), 16, 80, "width")
            number(obj.get("height"), 30, 400, "height")
            if obj["y"] + obj["height"] > FLOOR or not obj["width"] / 2 <= obj["x"] <= WIDTH - obj["width"] / 2:
                raise ValueError("ladder must fit inside the world")
        elif obj["kind"] == "fan":
            keys(obj, ("id", "kind", "x", "y", "force", "range", "angle", "enabled", "label"))
            for name, default, low, high in (("force", 500, 0, 1500), ("range", 180, 30, 400), ("angle", 0, -180, 180)):
                obj[name] = number(obj.get(name, default), low, high, name)
            obj.setdefault("enabled", True)
            if type(obj["enabled"]) is not bool:
                raise ValueError("enabled must be boolean")
        else:
            keys(obj, ("id", "kind", "x", "y", "label"))
        world["objects"].append(obj)
    elif operation == "remove":
        text(args.get("id"), 40, "id")
        if not any(o["id"] == args.get("id") for o in world["objects"]):
            raise ValueError("object does not exist")
        world["objects"] = [o for o in world["objects"] if o["id"] != args["id"]]
    elif operation in {"controller", "physics"}:
        values = args.get("values")
        limits = {"speed": (0, 180), "balance": (0, 1), "stride": (0, 24), "jump": (0, 450)} if operation == "controller" else {"gravity": (100, 1600)}
        keys(values, limits)
        if not values:
            raise ValueError("values must not be empty")
        for name, value in values.items():
            number(value, *limits[name], name)
        (world["controller"] if operation == "controller" else world).update(values)
    elif operation == "behavior":
        name = text(args.get("name"), 40, "name")
        steps = args.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
            raise ValueError("behavior requires 1..8 steps")
        total = 0
        for step in steps:
            action, frames, _ignored = validate_action(step)
            if action == "behavior":
                raise ValueError("nested behaviors are not supported")
            total += frames
        if total > 960 or (name not in world["behaviors"] and len(world["behaviors"]) >= 12):
            raise ValueError("behavior limit: 960 frames, 12 named behaviors")
        world["behaviors"][name] = copy.deepcopy(steps)
    else:
        raise ValueError("operation must be add, remove, controller, physics, or behavior")
    world["motion"] = []
    return {"kind": "evolution", "operation": operation, "change": copy.deepcopy(args), "verified": "configuration saved; behavior quality requires a physical test"}


def set_goal(world, args):
    keys(args, ("x", "tolerance", "label"))
    number(args.get("x"), 20, 980, "x")
    number(args.get("tolerance", 25), 5, 100, "tolerance")
    world["goal"] = {"x": args["x"], "tolerance": args.get("tolerance", 25),
                     "label": text(args.get("label", "Reach target"), 160, "label"), "set_at_tick": world["tick"]}
    return {"kind": "goal", "goal": copy.deepcopy(world["goal"])}


def reflect(world, args):
    keys(args, ("expected", "hypothesis", "next_test"))
    record = {name: text(args.get(name), 400, name) for name in ("expected", "hypothesis", "next_test")}
    record.update({"observed": observation(world), "evidence_revision": world["revision"],
                   "evidence_tick": world["tick"], "status": "hypothesis; not a verified lesson"})
    # Avoid recursively embedding prior reflection/history inside the new record.
    record["observed"].pop("latest_reflection", None)
    record["observed"].pop("last_action", None)
    record["observed"].pop("behaviors", None)
    world["reflections"] = (world["reflections"] + [record])[-20:]
    return {"kind": "reflection", "evidence_revision": world["revision"], "next_test": record["next_test"]}
