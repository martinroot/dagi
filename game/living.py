"""Agent-authored feedback controllers, materials and measured physical trials.

The controller language is a Python *expression* interpreted by a small bounded
AST walker. It never calls eval/exec, imports modules or accesses host objects.
No activities, destinations or progression levels are supplied by this module.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import operator
import re
from functools import lru_cache
from uuid import uuid4


DEFAULTS = {
    "projects": {}, "active_project": None, "project_state": {}, "project_started": 0, "project_error": None, "direction": {}, "event_queue": [], "appendages": [], "appendage_frames": [],
    "physics_engine": "legacy", "mechanisms": [], "contacts": {}, "emotion": {"valence": 0, "arousal": .25, "focus": .4}, "human": {}, "policies": {}, "active_policy": None, "policy_state": {}, "policy_error": None,
    "appearance": {"stroke": "#282d23", "accent": "#e6703a", "fill": "#ffffff",
                   "line_width": 5, "head_radius": 12, "joint_radius": 3.5, "trail": 0},
    "material": {"damping": .985, "vertical_damping": .995, "friction": .82,
                 "pose_strength": .08, "stiffness": 1, "iterations": 10},
    "life": {"running": False, "thinking": False, "iteration": 0, "limit": 5,
             "status": "paused", "intent": "", "error": None, "run_id": None},
    "evolution": [],
}


def upgrade(world):
    world.setdefault("project_scope","")
    from .workshop import DEFAULTS as WORKSHOP
    for key,value in WORKSHOP.items():world.setdefault(key,copy.deepcopy(value))
    for key, value in DEFAULTS.items():
        world.setdefault(key, copy.deepcopy(value))
    for saved in (world.get("previous"), *(world.get("draft",{}).get(k) for k in ("candidate","seed") if world.get("draft"))):
        if saved:
            for key in ("projects","active_project","project_state","project_started","appendages"):
                saved.setdefault(key,copy.deepcopy(DEFAULTS[key]))
            for key in ("body_control","substances","ropes","environment","character","art"):
                saved.setdefault(key,copy.deepcopy(WORKSHOP[key]))
    for obj in world.get("objects",[]):
        if obj["kind"]=="body" and "definition" not in obj:
            obj["definition"] = {k:copy.deepcopy(v) for k,v in obj.items() if k not in ("vx","vy","angle","angular_velocity","kind")}
    return world


FUNCTIONS = {"sin": math.sin, "cos": math.cos, "atan2": math.atan2,
             "sqrt": math.sqrt, "floor": math.floor, "abs": abs,
             "min": min, "max": max, "round": round, "len": len, "hypot": math.hypot,
             "clamp": lambda x, lo, hi: max(lo, min(hi, x)),
             "get": lambda obj, key, default=0: obj.get(key, default)}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
           ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


@lru_cache(maxsize=128)
def parse(source):
    if not isinstance(source, str) or not 1 <= len(source) <= 8000:
        raise ValueError("policy code must be a Python expression, 1..8000 characters")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("invalid policy expression: " + str(exc)[:180]) from exc
    nodes = list(ast.walk(tree))
    allowed = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Subscript,
               ast.Dict, ast.List, ast.Tuple, ast.BinOp, ast.UnaryOp, ast.BoolOp,
               ast.Compare, ast.IfExp, ast.Call, ast.USub, ast.UAdd, ast.Not,
               ast.And, ast.Or, *BINARY, *COMPARE)
    if len(nodes) > 600 or any(not isinstance(n, allowed) for n in nodes):
        raise ValueError("policy supports bounded expressions, dictionaries, indexing, math and conditions; no attributes, loops or imports")
    if any(isinstance(n, ast.Call) and (not isinstance(n.func, ast.Name) or n.func.id not in FUNCTIONS or n.keywords) for n in nodes):
        raise ValueError("policy calls only: " + ", ".join(FUNCTIONS))
    return tree.body


def evaluate(source, context):
    budget = [1200]

    def check(value):
        if isinstance(value, (int, float)) and (not math.isfinite(value) or abs(value) > 1e9):
            raise ValueError("policy number out of bounds")
        if isinstance(value, (str, list, tuple, dict)) and len(value) > 128:
            raise ValueError("policy value too large")
        return value

    def visit(node):
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("policy operation budget exceeded")
        if isinstance(node, ast.Constant):
            return check(node.value)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            if node.id not in context:
                raise ValueError("unknown policy variable: " + node.id)
            return context[node.id]
        if isinstance(node, ast.Subscript):
            return visit(node.value)[visit(node.slice)]
        if isinstance(node, (ast.List, ast.Tuple)):
            return check([visit(n) for n in node.elts])
        if isinstance(node, ast.Dict):
            if any(k is None for k in node.keys):
                raise ValueError("dictionary unpacking is not supported")
            return check({visit(k): visit(v) for k, v in zip(node.keys, node.values)})
        if isinstance(node, ast.IfExp):
            return visit(node.body if visit(node.test) else node.orelse)
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            return check(not value if isinstance(node.op, ast.Not) else -value if isinstance(node.op, ast.USub) else +value)
        if isinstance(node, ast.BoolOp):
            value = None
            for item in node.values:
                value = visit(item)
                if isinstance(node.op, ast.And) and not value or isinstance(node.op, ast.Or) and value:
                    break
            return value
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                raise ValueError("policy arithmetic requires numbers")
            if isinstance(node.op, ast.Pow) and abs(b) > 6:
                raise ValueError("policy exponent limit: 6")
            return check(BINARY[type(node.op)](a, b))
        if isinstance(node, ast.Compare):
            a = visit(node.left)
            for op, right in zip(node.ops, node.comparators):
                b = visit(right)
                if not COMPARE[type(op)](a, b):
                    return False
                a = b
            return True
        if isinstance(node, ast.Call):
            return check(FUNCTIONS[node.func.id](*(visit(n) for n in node.args)))
        raise ValueError("unsupported policy expression")

    try:
        result = visit(parse(source))
        if len(json.dumps(result, allow_nan=False)) > 8000:
            raise ValueError("policy result too large")
        return result
    except (TypeError, KeyError, IndexError, ArithmeticError, RecursionError) as exc:
        raise ValueError("policy runtime: " + str(exc)[:180]) from exc


def sensors(world):
    from .world import DT, _on_surface, observation
    obs = observation(world)
    hip = world["nodes"]["hip"]
    return {"t": world["tick"] * DT, "dt": DT, "x": hip["x"], "y": hip["y"],
            "vx": (hip["x"] - hip["px"]) / DT, "vy": (hip["y"] - hip["py"]) / DT,
            "grounded": obs["grounded"], "upright": obs["upright"],
            "goal": obs["goal"], "objects": copy.deepcopy(world["objects"]),
            "joints": {k: [p["x"], p["y"]] for k, p in world["nodes"].items()},
            "articulation":copy.deepcopy(world["articulation"]),"mechanisms":copy.deepcopy(world["mechanics_state"]),"energy":copy.deepcopy(world["energy"]),"body_control":copy.deepcopy(world["body_control"]),"ropes":[{k:r[k] for k in ("id","tension","length","broken")} for r in world["rope_frames"]],
            "contact_evidence":copy.deepcopy(world.get("contacts",{})),
            "contacts": {k: (k in world.get("contacts",{}).get("joints",[]) if world.get("physics_engine")=="chipmunk" else _on_surface(world,p,8)) for k,p in world["nodes"].items()}}


def command(world):
    if world.get("active_project"):
        from .director import command as project_command
        return project_command(world)
    name = world.get("active_policy")
    if not name:
        return {}
    result = evaluate(world["policies"][name]["code"], {"s": sensors(world), "m": world["policy_state"], "p": world["policies"][name].get("params", {})})
    return validate_control(world, result)


def validate_control(world, result):
    if not isinstance(result, dict) or set(result) - {"drive", "jump", "pose", "forces", "memory", "intent", "object_forces", "emotion", "gaze", "grip", "appendage_pose", "muscles", "servos", "joint_controls"}:
        raise ValueError("policy returns {drive,jump,pose,forces,memory,intent,object_forces}")
    from .world import number
    from .embodiment import validate as validate_muscles
    validate_muscles(world,result)
    number(result.get("drive", 0), -1, 1, "drive")
    if type(result.get("jump", False)) is not bool:
        raise ValueError("jump must be boolean")
    for field, limit in (("pose", 160), ("forces", 2000), ("object_forces", 2000)):
        entries = result.get(field, {})
        if not isinstance(entries, dict) or len(entries) > 32:
            raise ValueError(field + " must be a small dictionary")
        for key, vector in entries.items():
            if field != "object_forces" and key not in world["nodes"]:
                raise ValueError("unknown joint: " + str(key))
            if field == "object_forces" and not any(o["id"] == key and o["kind"] == "body" for o in world["objects"]):
                raise ValueError("unknown physical body: " + str(key))
            if not isinstance(vector, list) or len(vector) != 2:
                raise ValueError(field + " requires [x,y] vectors")
            for v in vector:
                number(v, -limit, limit, field)
    memory = result.get("memory", world["policy_state"])
    if not isinstance(memory, dict) or len(json.dumps(memory, allow_nan=False)) > 2048:
        raise ValueError("policy memory must be a JSON dictionary <=2048 characters")
    intent = result.get("intent", "")
    if not isinstance(intent, str) or len(intent) > 100:
        raise ValueError("policy intent must be text <=100 characters")
    poses = result.get("appendage_pose", {})
    if not isinstance(poses,dict) or set(poses)-{p["id"] for p in world["appendages"]}:
        raise ValueError("appendage_pose references unknown part")
    for value in poses.values():number(value,-6.3,6.3,"appendage angle")
    emotion = result.get("emotion", {})
    if not isinstance(emotion, dict) or set(emotion) - {"valence", "arousal", "focus", "surprise", "mouth", "squint", "tilt"}:
        raise ValueError("emotion uses valence -1..1, arousal/focus 0..1")
    for key,value in emotion.items():
        number(value, -.5 if key=="tilt" else -1 if key=="valence" else 0, .5 if key=="tilt" else 1, key)
    world["emotion"].update(emotion)
    grip = result.get("grip")
    if grip is not None:
        if not isinstance(grip, dict) or set(grip)-{"object","hand"} or grip.get("hand","right_hand") not in ("left_hand","right_hand"):
            raise ValueError("grip uses {object:id,hand:left_hand|right_hand}; omit to release")
    if "gaze" in result:
        if not isinstance(result["gaze"],list) or len(result["gaze"])!=2:
            raise ValueError("gaze is [x,y]")
        for value in result["gaze"]: number(value,-1000,2000,"gaze")
        world["emotion"]["gaze"] = result["gaze"]
    world["policy_state"] = copy.deepcopy(memory)
    world["life"]["intent"] = intent
    return result


def design(world, args):
    """General extension surface. Changes are staged by the studio, never live."""
    from .world import keys, number, text
    operation = args.get("operation")
    if operation == "policy":
        keys(args, ("operation", "name", "code", "description", "activate", "params"))
        name = text(args.get("name"), 40, "policy name")
        if name in world["projects"]:raise ValueError("use a policy name distinct from saved project names")
        parse(args.get("code"))
        description = text(args.get("description"), 200, "description")
        if name not in world["policies"] and len(world["policies"]) >= 12:
            raise ValueError("maximum 12 named policies")
        if type(args.get("activate", True)) is not bool:
            raise ValueError("activate must be boolean")
        params = args.get("params", {})
        if not isinstance(params,dict) or len(params)>16:
            raise ValueError("params must be a small numeric dictionary")
        for key,value in params.items():
            text(key,40,"parameter name");number(value,-2000,2000,"parameter value")
        world["policies"][name] = {"params": params, "code": args["code"], "description": description,
                                   "version": hashlib.sha256(args["code"].encode()).hexdigest()[:12]}
        if args.get("activate", True):
            world["active_policy"] = name
            world["active_project"] = None
            world["direction"] = {}
            world["policy_state"] = {}
            world["policy_error"] = None
        # Exercise the real initial input now; tests also run subsequent states.
        probe = copy.deepcopy(world)
        probe["active_policy"] = name
        command(probe)
    elif operation == "appearance":
        keys(args, ("operation", "values"))
        values = args.get("values")
        keys(values, DEFAULTS["appearance"])
        if not values:
            raise ValueError("appearance values are empty")
        for k, v in values.items():
            if k in ("stroke", "accent", "fill"):
                if not isinstance(v, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", v) is None:
                    raise ValueError("appearance colors use #RRGGBB")
            else:
                number(v, *{"line_width": (2, 9), "head_radius": (8, 17), "joint_radius": (0, 5), "trail": (0, 12)}[k], k)
        world["appearance"].update(values)
    elif operation == "material":
        keys(args, ("operation", "values"))
        limits = {"damping": (.9, .999), "vertical_damping": (.9, .999), "friction": (0, 1),
                  "pose_strength": (.01, .2), "stiffness": (.3, 1), "iterations": (4, 16)}
        values = args.get("values")
        keys(values, limits)
        if not values:
            raise ValueError("material values are empty")
        for k, v in values.items():
            number(v, *limits[k], k)
            if k == "iterations" and type(v) is not int:
                raise ValueError("iterations must be integer")
        world["material"].update(values)
    elif operation in ("joint","body"):
        from .workshop import joint,body
        return (joint if operation=="joint" else body)(world,args)

    else:
        raise ValueError("design operation must be policy, appearance, material or body")
    return {"kind": "design", "operation": operation}


def advance(world, frames=6, cancelled=lambda: False, simulator=None, diagnostics=True):
    from .world import DT, _step, frame, observation
    if simulator is None and world.get("physics_engine")=="chipmunk":
        from .rigid import RigidSimulator
        simulator = RigidSimulator(world)
    frames_out = [frame(world,presentation=False)] if diagnostics else []
    samples = []
    for i in range(frames):
        if cancelled():
            raise ValueError("physical trial cancelled")
        output = command(world)
        if simulator is None and output.get("jump") and observation(world)["grounded"]:
            for p in world["nodes"].values():
                p["py"] = p["y"] + world["controller"]["jump"] * DT
        if simulator is not None:
            simulator.step(output)
        else:
            _step(world, output.get("drive", 0), control=output)
        if i % 6 == 0 or i == frames - 1:
            if not diagnostics: continue
            frames_out.append(frame(world,presentation=False))
            sample = observation(world)
            hip = world["nodes"]["hip"]
            from .world import _on_surface
            from .character import bone_lengths
            sample["speed"] = math.hypot(hip["x"] - hip["px"], hip["y"] - hip["py"]) / DT
            sample["bone_error"] = max(abs(math.hypot(world["nodes"][a]["x"] - world["nodes"][b]["x"], world["nodes"][a]["y"] - world["nodes"][b]["y"]) - length) for a, b, length in bone_lengths(world))
            sample["foot_slip"] = sum(abs(world["nodes"][name]["x"] - world["nodes"][name]["px"]) / DT
                                      for name in ("left_foot", "right_foot") if _on_surface(world, world["nodes"][name], 7))
            samples.append(sample)
    if diagnostics:world["motion"] = (world["motion"] + frames_out)[-122:]
    return samples


def body_extent(obj):
    if obj["shape"]=="polygon":return max(abs(p[0]) for p in obj["vertices"]),max(abs(p[1]) for p in obj["vertices"])
    return (obj["radius"], obj["radius"]) if obj["shape"] == "circle" else (obj["width"] / 2, obj["height"] / 2)


def integrate_objects(world, forces):
    from .world import DT, FLOOR, WIDTH
    bodies = [o for o in world["objects"] if o["kind"] == "body"]
    for obj in bodies:
        fx, fy = forces.get(obj["id"], [0, 0])
        obj["vx"] = max(-500, min(500, (obj["vx"] + fx / obj["mass"] * DT) * .995))
        obj["vy"] = max(-600, min(600, obj["vy"] + (world["gravity"] + fy / obj["mass"]) * DT))
        obj["x"] += obj["vx"] * DT
        obj["y"] += obj["vy"] * DT
        rx, ry = body_extent(obj)
        if obj["y"] > FLOOR - ry:
            obj["y"] = FLOOR - ry
            obj["vy"] = -abs(obj["vy"]) * obj["restitution"] if abs(obj["vy"]) > 25 else 0
            obj["vx"] *= world["material"]["friction"]
        if obj["y"] < ry:
            obj["y"] = ry
            obj["vy"] = abs(obj["vy"]) * obj["restitution"]
        if obj["x"] < rx or obj["x"] > WIDTH - rx:
            obj["x"] = max(rx, min(WIDTH - rx, obj["x"]))
            obj["vx"] *= -obj["restitution"]
    # AABB broad phase with circle narrow phase for round/round bodies.
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            ax, ay = body_extent(a)
            bx, by = body_extent(b)
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            overlap_x, overlap_y = ax + bx - abs(dx), ay + by - abs(dy)
            if overlap_x <= 0 or overlap_y <= 0:
                continue
            if a["shape"] == b["shape"] == "circle":
                distance = max(.001, math.hypot(dx, dy))
                overlap = ax + bx - distance
                if overlap <= 0:
                    continue
                nx, ny = (dx / distance, dy / distance) if distance > .001 else (1, 0)
            elif overlap_x < overlap_y:
                nx, ny, overlap = (1 if dx >= 0 else -1), 0, overlap_x
            else:
                nx, ny, overlap = 0, (1 if dy >= 0 else -1), overlap_y
            inv_a, inv_b = 1 / a["mass"], 1 / b["mass"]
            scale = overlap / (inv_a + inv_b)
            a["x"] -= nx * scale * inv_a
            a["y"] -= ny * scale * inv_a
            b["x"] += nx * scale * inv_b
            b["y"] += ny * scale * inv_b
            speed = (b["vx"] - a["vx"]) * nx + (b["vy"] - a["vy"]) * ny
            if speed < 0:
                impulse = -(1 + min(a["restitution"], b["restitution"])) * speed / (inv_a + inv_b)
                a["vx"] -= impulse * inv_a * nx
                a["vy"] -= impulse * inv_a * ny
                b["vx"] += impulse * inv_b * nx
                b["vy"] += impulse * inv_b * ny


def collide_body(obj, point, radius):
    """Two-way point/body contact; dynamic objects can be pushed by the skeleton."""
    from .world import DT
    rx, ry = body_extent(obj)
    dx, dy = point["x"] - obj["x"], point["y"] - obj["y"]
    if obj["shape"] == "circle":
        distance = max(.001, math.hypot(dx, dy))
        overlap = rx + radius - distance
        if overlap <= 0:
            return
        nx, ny = (dx / distance, dy / distance) if distance > .001 else (1, 0)
    else:
        ox, oy = rx + radius - abs(dx), ry + radius - abs(dy)
        if ox <= 0 or oy <= 0:
            return
        if ox < oy:
            nx, ny, overlap = (1 if dx >= 0 else -1), 0, ox
        else:
            nx, ny, overlap = 0, (1 if dy >= 0 else -1), oy
    share = obj["mass"] / (obj["mass"] + 2)
    point["x"] += nx * overlap * share
    point["y"] += ny * overlap * share
    obj["x"] -= nx * overlap * (1 - share)
    obj["y"] -= ny * overlap * (1 - share)
    # Transfer approach velocity only. Do not inject an impulse every solver pass.
    vx, vy = (point["x"] - point["px"]) / DT, (point["y"] - point["py"]) / DT
    approach = (vx - obj["vx"]) * nx + (vy - obj["vy"]) * ny
    if approach < 0:
        obj["vx"] += nx * approach * (1 - share) * .2
        obj["vy"] += ny * approach * (1 - share) * .2


def trial(world, frames=None, cancelled=lambda: False):
    frames = frames if frames is not None else (720 if world.get("active_project") else 240)
    clone = copy.deepcopy(world)
    clone["project_scope"] = uuid4().hex  # Offline trials never share mutable JS globals with the live world.
    clone["draft"] = None
    start = sensors(clone)
    initial_objects={o["id"]:copy.deepcopy(o) for o in clone["objects"]}
    try:
        samples = advance(clone, frames, cancelled)
        last = sensors(clone)
        finite = all(math.isfinite(v) for p in clone["nodes"].values() for v in p.values())
        path = [start] + [s["position"] for s in samples]
        travel = sum(math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(path, path[1:]))
        objects={}
        for o in clone["objects"]:
            first=initial_objects[o["id"]]
            path=[first]+[next((p for p in sample["objects"] if p["id"]==o["id"]),o) for sample in samples]+[o]
            objects[o["id"]]={"dx":round(o["x"]-first["x"],3),"dy":round(o["y"]-first["y"],3),"end_x":round(o["x"],3),"end_y":round(o["y"],3),"min_x":round(min(p["x"] for p in path),3),"max_x":round(max(p["x"] for p in path),3),"min_y":round(min(p["y"] for p in path),3),"max_y":round(max(p["y"] for p in path),3),"rotation":round(o.get("angle",0)-first.get("angle",0),3)}
        rope_results={r["id"]:{"broken":r["broken"],"length":round(r["length"],3),"peak_tension":max((p["tension"] for frame in clone["motion"] for p in frame.get("ropes",[]) if p["id"]==r["id"]),default=r["tension"])} for r in clone["rope_frames"]}
        return {"passed": finite, "objects":objects,"ropes":rope_results, "frames": frames, "mode":clone["body_control"]["mode"], "muscle_work":round(clone["energy"]["muscle_work"]-world["energy"]["muscle_work"],4),"motor_work":round(clone["energy"]["motor_work"]-world["energy"]["motor_work"],4), "dx": round(last["x"] - start["x"], 2),
                "dy": round(last["y"] - start["y"], 2), "travel": round(travel, 2),
                "upright_ratio": round(sum(s["upright"] for s in samples) / len(samples), 3),
                "grounded_ratio": round(sum(s["grounded"] for s in samples) / len(samples), 3),
                "max_bone_error": round(max(s["bone_error"] for s in samples), 3),
                "speed_jitter": round(sum(abs(b["speed"] - a["speed"]) for a, b in zip(samples, samples[1:])) / max(1, len(samples) - 1), 3),
                "mean_foot_slip": round(sum(s["foot_slip"] for s in samples) / len(samples), 3),
                "end_x": round(last["x"], 2), "end_y": round(last["y"], 2),
                "scope": "Measured rollout of actual feedback code; these metrics do not rank aesthetic quality or usefulness."}
    except (ValueError, KeyError) as exc:
        return {"passed": False, "error": str(exc)[:240], "frames": frames}
