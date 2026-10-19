"""Declarative visual tools, bounded experiments, verified drafts and world releases."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from uuid import uuid4

from .living import design, trial
from .world import act, evolve, keys, number, observation, text, validate_action

LIVE_FIELDS = ("nodes", "tick", "gravity", "controller", "objects", "behaviors", "goal", "widgets", "components", "theme", "policies", "active_policy", "policy_state", "appearance", "material", "mechanisms", "projects", "active_project", "project_started", "project_state", "appendages", "body_control", "substances", "ropes", "environment")
TOOL_NAMES = {"game_inspect", "game_act", "game_evolve", "game_goal", "game_reflect", "game_build", "game_visual", "game_review"}


def snapshot(world):
    return {name: copy.deepcopy(world[name]) for name in LIVE_FIELDS}


def configuration(world):
    result = snapshot(world)
    for key in ("nodes", "tick", "policy_state", "project_state", "project_started"):
        result.pop(key, None)
    result["objects"] = [copy.deepcopy(o.get("definition",o)) if o["kind"]=="body" else copy.deepcopy(o) for o in result["objects"]]
    for obj in result["objects"]:
        if obj.get("kind")=="body" or obj.get("shape") in ("circle","rect","polygon"):
            for key in ("vx","vy","angular_velocity","definition"):
                obj.pop(key,None)
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_target(target, world):
    keys(target, ("type", "name", "action", "frames", "text", "event"))
    kind = target.get("type")
    if kind == "project":
        keys(target,("type","name","event"))
        if target.get("name") not in world["projects"]:raise ValueError("unknown project")
        if "event" in target:text(target["event"],60,"project event")
    elif kind == "policy":
        keys(target,("type","name"))
        if target.get("name") not in world["policies"]:raise ValueError("unknown feedback policy")
    elif kind == "behavior":
        keys(target, ("type", "name"))
        text(target.get("name"), 40, "behavior name")
        if target["name"] not in world["behaviors"]:
            raise ValueError("button/skill references an unknown behavior")
    elif kind == "action":
        keys(target, ("type", "action", "frames"))
        validate_action({name: value for name, value in target.items() if name != "type"})
        if target["action"] == "behavior":
            raise ValueError("use type=behavior and name")
    elif kind == "prompt":
        keys(target, ("type", "text"))
        text(target.get("text"), 500, "button prompt")
    elif kind == "tool":
        keys(target, ("type", "name"))
        if not isinstance(target.get("name"), str) or target["name"] not in TOOL_NAMES:
            raise ValueError("unknown game tool binding")
    else:
        raise ValueError("target type must be action, behavior, prompt, or tool")


def validate_widget(widget, world):
    keys(widget, ("id", "kind", "x", "y", "width", "height", "title", "body", "items", "target", "icon", "hotkey"))
    text(widget.get("id"), 40, "widget id")
    kind = widget.get("kind")
    if not isinstance(kind, str) or kind not in {"panel", "skill", "todo", "button"}:
        raise ValueError("widget kind must be panel, skill, todo, or button")
    text(widget.get("title"), 60, "title")
    if "icon" in widget:text(widget["icon"],16,"skill icon")
    if "hotkey" in widget and widget["hotkey"] not in list("123456789"):raise ValueError("skill hotkey is1..9")
    number(widget.get("x"), 0, 1000, "x")
    number(widget.get("y"), 40, 520, "y")
    number(widget.get("width"), 110, 350, "width")
    number(widget.get("height"), 42, 320, "height")
    if widget["x"] + widget["width"] > 1000 or widget["y"] + widget["height"] > 535:
        raise ValueError("widget must fit above the floor")
    if "body" in widget:
        text(widget["body"], 280, "body")
    if kind == "todo":
        items = widget.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise ValueError("todo requires 1..8 items")
        ids = set()
        for item in items:
            keys(item, ("id", "text", "done"))
            text(item.get("id"), 40, "item id")
            text(item.get("text"), 100, "item text")
            if item["id"] in ids or type(item.get("done", False)) is not bool:
                raise ValueError("todo item ids must be unique and done must be boolean")
            ids.add(item["id"])
            item.setdefault("done", False)
    elif "items" in widget:
        raise ValueError("only todo widgets have items")
    if kind in {"button", "skill"}:
        validate_target(widget.get("target"), world)
    elif "target" in widget:
        raise ValueError("only button/skill widgets have a target")


def validate_component(component, world):
    keys(component, ("id", "title", "x", "y", "width", "height", "code", "events", "layer"))
    text(component.get("id"), 40, "component id")
    text(component.get("title"), 60, "component title")
    text(component.get("code"), 12000, "JavaScript function body")
    for name, low, high in (("x", 0, 1000), ("y", 40, 535), ("width", 40, 1000), ("height", 30, 495)):
        number(component.get(name), low, high, name)
    if component["x"] + component["width"] > 1000 or component["y"] + component["height"] > 535:
        raise ValueError("component must fit above the floor")
    component.setdefault("layer", "foreground")
    if component["layer"] not in ("background", "foreground"):
        raise ValueError("component layer must be background or foreground")
    events = component.setdefault("events", [])
    if not isinstance(events, list) or len(events) > 8:
        raise ValueError("component supports at most eight named events")
    ids = set()
    for event in events:
        keys(event, ("id", "label", "target"))
        text(event.get("id"), 40, "event id")
        text(event.get("label"), 80, "event label")
        if event["id"] in ids:
            raise ValueError("event ids must be unique")
        ids.add(event["id"])
        if "target" in event:
            validate_target(event["target"], world)


def visual_edit(world, args):
    keys(args, ("operation", "widget", "component", "id", "item_id", "done", "values"))
    operation = args.get("operation")
    if operation == "component":
        keys(args, ("operation", "component"))
        component = copy.deepcopy(args.get("component"))
        validate_component(component, world)
        component["code_hash"] = digest(component["code"])
        index = next((i for i, old in enumerate(world["components"]) if old["id"] == component["id"]), None)
        if index is None:
            if len(world["components"]) >= 8:
                raise ValueError("limit: eight authored components")
            world["components"].append(component)
        else:
            world["components"][index] = component
    elif operation == "remove_component":
        keys(args, ("operation", "id"))
        text(args.get("id"), 40, "id")
        if not any(c["id"] == args["id"] for c in world["components"]):
            raise ValueError("component not found")
        world["components"] = [c for c in world["components"] if c["id"] != args["id"]]
    elif operation == "widget":
        keys(args, ("operation", "widget"))
        widget = copy.deepcopy(args.get("widget"))
        validate_widget(widget, world)
        old = next((i for i, w in enumerate(world["widgets"]) if w["id"] == widget["id"]), None)
        if old is None:
            if len(world["widgets"]) >= 12:
                raise ValueError("limit: 12 visual widgets")
            world["widgets"].append(widget)
        else:
            world["widgets"][old] = widget
    elif operation == "remove_widget":
        keys(args, ("operation", "id"))
        text(args.get("id"), 40, "id")
        if not any(w["id"] == args["id"] for w in world["widgets"]):
            raise ValueError("widget not found")
        world["widgets"] = [w for w in world["widgets"] if w["id"] != args["id"]]
    elif operation == "todo":
        keys(args, ("operation", "id", "item_id", "done"))
        text(args.get("id"), 40, "id")
        text(args.get("item_id"), 40, "item_id")
        if type(args.get("done")) is not bool:
            raise ValueError("done must be boolean")
        item = next((i for w in world["widgets"] if w["id"] == args["id"] and w["kind"] == "todo"
                     for i in w["items"] if i["id"] == args["item_id"]), None)
        if item is None:
            raise ValueError("todo item not found")
        item["done"] = args["done"]
    elif operation == "theme":
        keys(args, ("operation", "values"))
        values = args.get("values")
        keys(values, ("background", "accent"))
        if not values or any(not isinstance(v, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", v) is None for v in values.values()):
            raise ValueError("theme uses #RRGGBB colors")
        world["theme"].update(values)
    else:
        raise ValueError("visual operation must be component, remove_component, widget, remove_widget, todo, or theme")
    return {"kind": "visual_edit", "operation": operation, "id": args.get("id") or args.get("widget", {}).get("id")}


def edit(world, change):
    if not isinstance(change, dict):
        raise ValueError("change must be an object")
    if change.get("operation") in {"body_control","substance","rope","remove_rope","environment"}:
        from .workshop import edit as workshop_edit
        return workshop_edit(world,change)
    if change.get("operation") == "project":
        from .director import define
        return define(world, change)
    if change.get("operation") in {"appendage","remove_appendage","remove_body","remove_joint"}:
        from .director import anatomy
        return anatomy(world,change)
    if change.get("operation") in {"policy", "appearance", "material", "body", "joint"}:
        return design(world, change)
    if change.get("operation") in ("component", "remove_component", "widget", "remove_widget", "todo", "theme"):
        return visual_edit(world, change)
    return evolve(world, change)


def _luminance(color):
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(a * b for a, b in zip(values, (.2126, .7152, .0722)))


def review(world):
    """Reproducible geometry/contrast diagnostics, never a fabricated vision score."""
    findings = []
    widgets = world["widgets"]
    for i, widget in enumerate(widgets):
        validate_widget(copy.deepcopy(widget), world)
        line_chars = max(10, int((widget["width"] - 16) / 6.5))
        needed = 36 + math.ceil(len(widget["title"]) / line_chars) * 17
        if widget.get("body"):
            needed += math.ceil(len(widget["body"]) / line_chars) * 16
        if widget["kind"] == "todo":
            needed += sum(max(24, math.ceil(len(item["text"]) / line_chars) * 16 + 5) for item in widget["items"])
        if widget["kind"] in {"skill", "button"}:
            target = widget["target"]
            binding = target["type"] + " / " + target.get("name", target.get("action", "prompt"))
            needed += math.ceil(len(binding) / line_chars) * 17
        if widget["height"] < needed:
            findings.append({"id": widget["id"], "issue": "content_height", "needed": needed})
        for other in widgets[i + 1:]:
            overlap = min(widget["x"] + widget["width"], other["x"] + other["width"]) - max(widget["x"], other["x"]) > 4 and min(widget["y"] + widget["height"], other["y"] + other["height"]) - max(widget["y"], other["y"]) > 4
            if overlap:
                findings.append({"id": widget["id"], "other": other["id"], "issue": "widget_overlap"})
        if any(widget["x"] <= p["x"] <= widget["x"] + widget["width"] and widget["y"] <= p["y"] <= widget["y"] + widget["height"] for p in world["nodes"].values()):
            findings.append({"id": widget["id"], "issue": "body_occlusion"})
    backdrop=(world.get("environment") or {}).get("sky_bottom",world["theme"]["background"])
    contrast = (max(_luminance(backdrop), _luminance(world["appearance"]["stroke"])) + .05) / (min(_luminance(backdrop), _luminance(world["appearance"]["stroke"])) + .05)
    for component in world["components"]:
        validate_component({k: v for k, v in copy.deepcopy(component).items() if k != "code_hash"}, world)
        if component["layer"] == "foreground" and any(component["x"] <= p["x"] <= component["x"] + component["width"] and component["y"] <= p["y"] <= component["y"] + component["height"] for p in world["nodes"].values()):
            findings.append({"id": component["id"], "issue": "component_body_occlusion"})
    if contrast < 4.5:
        findings.append({"issue": "body_background_contrast", "ratio": round(contrast, 2)})
    browser = copy.deepcopy(world.get("browser_report"))
    if browser:
        browser["stale"] = browser["render_key"] != digest(configuration(world))
        if not browser["stale"]:
            if browser["overflow"]:
                findings.append({"issue": "browser_reported_page_overflow", "source": "untrusted browser measurement"})
            for issue in browser["issues"]:
                if issue.startswith("content_overflow:"):
                    findings.append({"issue": issue, "source": "untrusted browser measurement"})
    executions = {r["id"]: r for r in browser.get("components", [])} if browser and not browser["stale"] else {}
    component_status = [{"id": c["id"], "code_hash": c["code_hash"],
                         "status": executions[c["id"]]["status"] if c["id"] in executions else "pending",
                         "detail": executions[c["id"]]["detail"] if c["id"] in executions else "Open the world preview so its authored JavaScript can be tested in a browser worker."} for c in world["components"]]
    for result in component_status:
        if result["status"] == "error":
            findings.append({"id": result["id"], "issue": "component_execution", "detail": result["detail"]})
    return {"passed": not findings, "findings": findings[:24], "body_contrast": round(contrast, 2),
            "component_execution": component_status,
            "method": "scene geometry, declared content sizing and color luminance; not screenshot aesthetics",
            "browser": browser, "scope": "layout/readability checks; no pixel vision input to the LLM"}


def _simulate(world, cancelled):
    clone = copy.deepcopy(world)
    clone["history"], clone["reflections"], clone["draft"], clone["motion"] = [], [], None, []
    act(clone, {"action": "idle", "frames": 90}, cancelled)
    state = observation(clone)
    finite = all(math.isfinite(v) for p in clone["nodes"].values() for v in p.values())
    return {"finite": finite, "upright": state["upright"], "grounded": state["grounded"], "position": state["position"]}


def build(world, args, cancelled=lambda: False):
    keys(args, ("operation", "objective", "changes"))
    operation = args.get("operation")
    draft = world["draft"]
    if operation == "begin":
        keys(args, ("operation", "objective"))
        if draft:
            raise ValueError("a draft already exists; inspect, edit or discard it")
        world["draft"] = {"id": uuid4().hex, "state": "building", "objective": text(args.get("objective"), 300, "objective"),
                          "base": digest(configuration(world)), "seed": snapshot(world), "candidate": snapshot(world), "edits": 0, "test_count": 0, "report": None}
    elif operation == "discard":
        keys(args, ("operation",))
        if draft and draft["state"] == "scheduled":
            raise ValueError("activation is in progress; cancel the run first")
        world["draft"] = None
    elif operation == "edit":
        keys(args, ("operation", "changes"))
        if not draft or draft["state"] == "scheduled":
            raise ValueError("begin a draft before editing")
        changes = args.get("changes")
        if not isinstance(changes, list) or not 1 <= len(changes) <= 24 or draft["edits"] + len(changes) > 24:
            raise ValueError("use 1..24 changes per call, at most 24 per draft")
        candidate = copy.deepcopy(world)
        candidate.update(copy.deepcopy(draft["candidate"]))
        for change in changes:
            edit(candidate, change)
        draft.update(candidate=snapshot(candidate), state="building", report=None, edits=draft["edits"] + len(changes))
    elif operation == "test":
        keys(args, ("operation",))
        if not draft or draft["state"] == "scheduled" or draft["test_count"] >= 3:
            raise ValueError("begin a draft; at most three tests are allowed per draft")
        if draft["base"] != digest(configuration(world)):
            raise ValueError("live world changed; discard and rebuild against current state")
        candidate = copy.deepcopy(world)
        candidate.update(copy.deepcopy(draft["candidate"]))
        baseline_world = copy.deepcopy(world)
        baseline_world.update(copy.deepcopy(draft.get("seed",snapshot(world))))
        baseline, after = _simulate(baseline_world, cancelled), _simulate(candidate, cancelled)
        visual = review(candidate)
        checks = {"changed": digest(configuration(candidate)) != draft["base"], "finite_physics": after["finite"],
                  "posture_no_regression": candidate["body_control"]["mode"]=="physical" or not baseline["upright"] or after["upright"],
                  "layout_readable": visual["passed"], "goal_preserved": candidate["goal"] == world["goal"]}
        checks["authored_components_executed"] = all(c["status"] == "passed" for c in visual["component_execution"])
        policy_before, policy_after = trial(baseline_world, cancelled=cancelled), trial(candidate, cancelled=cancelled)
        checks["feedback_policy_executes"] = policy_after["passed"]
        checks["feedback_posture_no_regression"] = candidate["body_control"]["mode"]=="physical" or not policy_before["passed"] or not policy_after["passed"] or policy_after["upright_ratio"] >= min(.65, policy_before.get("upright_ratio", 0))
        skill_tests = []
        for name, steps in candidate["behaviors"].items():
            clone = copy.deepcopy(candidate)
            outcome = act(clone, {"action": "behavior", "name": name}, cancelled)
            healthy = all(math.isfinite(v) for p in clone["nodes"].values() for v in p.values())
            checks[f"program:{name}"] = healthy
            skill_tests.append({"behavior": name, "displacement_x": outcome["displacement_x"], "finite": healthy, "upright": outcome["upright"], "scope": "actual saved program executed; semantic task correctness unverified"})
        for widget in candidate["widgets"]:
            if widget["kind"] == "skill" and widget["target"]["type"] == "behavior":
                clone = copy.deepcopy(candidate)
                outcome = act(clone, {"action": "behavior", "name": widget["target"]["name"]}, cancelled)
                healthy = all(math.isfinite(v) for p in clone["nodes"].values() for v in p.values())
                checks[f"skill:{widget['id']}"] = healthy
                skill_tests.append({"widget_id": widget["id"], "behavior": widget["target"]["name"], "displacement_x": outcome["displacement_x"],
                                    "finite": healthy, "upright": outcome["upright"], "scope": "program executes with finite physics; task correctness remains unverified"})
        draft["test_count"] += 1
        draft["state"] = "tested"
        draft["report"] = {"passed": all(checks.values()), "checks": checks, "baseline": baseline, "candidate": after,
                           "visual": visual, "skill_tests": skill_tests, "feedback_trial": {"baseline": policy_before, "candidate": policy_after}, "candidate_hash": digest(draft["candidate"]),
                           "scope": "bounded physical health, preserved goal and readable layout; not proof of general intelligence or all user requirements"}
    elif operation == "commit":
        keys(args, ("operation",))
        if not draft or draft["state"] != "tested" or not draft["report"] or not draft["report"]["passed"]:
            raise ValueError("a passing draft test is required before release")
        if draft["base"] != digest(configuration(world)) or draft["report"]["candidate_hash"] != digest(draft["candidate"]):
            raise ValueError("test evidence is stale; test the exact current draft")
        draft["state"] = "scheduled"
        draft["activate_at"] = time.time() + 3.2
    else:
        raise ValueError("build operation must be begin, edit, test, commit, or discard")
    return {"kind": "build", "operation": operation, "build_id": world["draft"]["id"] if world["draft"] else None}


def activate(world, args):
    draft = world["draft"]
    if not draft or draft["id"] != args.get("id") or draft["state"] != "scheduled":
        raise ValueError("scheduled release no longer exists")
    if time.time() < draft["activate_at"]:
        raise ValueError("release countdown is still running")
    if draft["base"] != digest(configuration(world)) or draft["report"]["candidate_hash"] != digest(draft["candidate"]):
        raise ValueError("live world or candidate changed after testing")
    world["previous"] = snapshot(world)
    live_nodes, live_tick = copy.deepcopy(world["nodes"]), world["tick"]
    old_objects = {o["id"]: copy.deepcopy(o) for o in world["objects"]}
    old_ropes={r["id"]:copy.deepcopy(r) for r in world["ropes"]}
    old_joints={j["id"]:copy.deepcopy(j) for j in world["mechanisms"]}
    same_policy = world["active_policy"]==draft["candidate"]["active_policy"] and world["policies"]==draft["candidate"]["policies"]
    same_project = world["active_project"]==draft["candidate"]["active_project"] and world["projects"]==draft["candidate"]["projects"]
    project_state,project_started = copy.deepcopy(world["project_state"]),world["project_started"]
    memory = copy.deepcopy(world["policy_state"])
    world.update(copy.deepcopy(draft["candidate"]))
    candidate_nodes=world["nodes"]
    candidate_nodes.update(live_nodes)
    for side in ("left","right"):
        name=side+"_toe"
        if name in candidate_nodes and name not in live_nodes:
            foot=live_nodes[side+"_foot"]
            candidate_nodes[name]={k:foot[k]+(13 if k in ("x","px") else 0) for k in foot}
    world["nodes"], world["tick"] = candidate_nodes, live_tick
    world["rope_state"]={k:v for k,v in world["rope_state"].items() if any(r["id"]==k and old_ropes.get(k)==r for r in world["ropes"])}
    world["mechanics_state"]={k:v for k,v in world["mechanics_state"].items() if any(j["id"]==k and old_joints.get(k)==j for j in world["mechanisms"])}
    if same_policy: world["policy_state"] = memory
    if same_project:
        world["project_state"],world["project_started"]=project_state,project_started
    else:
        world["project_state"],world["project_started"]={},live_tick
        world["direction"]={}
        world["event_queue"]=[]
    world["project_error"]=None
    for i,obj in enumerate(world["objects"]):
        old=old_objects.get(obj["id"])
        if old and old.get("definition")==obj.get("definition") and obj["kind"]=="body":
            for field in ("x","y","vx","vy","angle","angular_velocity"):
                if field in old:obj[field]=old[field]
    world["version"] += 1
    world["policy_error"] = None
    world["failed_policy"] = None
    world["life"]["error"] = None
    world["motion"] = []
    world["last_release"] = {"id": draft["id"], "version": world["version"], "objective": draft["objective"],
                             "activated_at": time.time(), "checks": draft["report"]["checks"], "report": copy.deepcopy(draft["report"])}
    world["evolution"] = (world["evolution"] + [{"version": world["version"], "objective": draft["objective"], "at": time.time(), "policy": world["active_policy"], "project":world["active_project"], "trial": copy.deepcopy(draft["report"].get("feedback_trial"))}])[-30:]
    world["browser_report"], world["draft"] = None, None
    return {"kind": "release", "version": world["version"], "build_id": args["id"]}


def abort_release(world, args):
    if world["draft"] and world["draft"]["id"] == args["id"]:
        world["draft"]["state"] = "tested"
        world["draft"]["release_error"] = "Run cancelled before activation; live world unchanged."
    return {"kind": "release_cancelled", "build_id": args["id"]}


def build_summary(world):
    draft = world["draft"]
    if not draft:
        return None
    return {k: copy.deepcopy(draft[k]) for k in ("id", "state", "objective", "edits", "test_count", "report", "activate_at", "countdown_ms", "release_error", "improvement_mode", "baseline_complexity_score") if k in draft}


def human_prompt(world, args):
    keys(args, ("widget_id", "component_id", "event_id", "item_id", "version"))
    if type(args.get("version")) is not int or args["version"] != world["version"]:
        raise ValueError("world changed; refresh its controls before clicking")
    if "component_id" in args:
        component = next((c for c in world["components"] if c["id"] == args["component_id"]), None)
        event = next((e for e in component["events"] if e["id"] == args.get("event_id")), None) if component else None
        if not event or "target" not in event:
            raise ValueError("component event has no declared agent action")
        return "The human clicked the visual control " + json.dumps({"title": event["label"], "target": event["target"]}, ensure_ascii=False) + ". Execute the declared action through the registry."
    widget = next((w for w in world["widgets"] if w["id"] == args.get("widget_id")), None)
    if not widget:
        raise ValueError("visual control no longer exists")
    if widget["kind"] == "todo":
        item = next((i for i in widget["items"] if i["id"] == args.get("item_id")), None)
        if not item:
            raise ValueError("todo item no longer exists")
        return "The human clicked a todo item. Apply game_visual with these arguments: " + json.dumps(
            {"operation": "todo", "id": widget["id"], "item_id": item["id"], "done": not item["done"]}, ensure_ascii=False)
    if widget["kind"] not in {"button", "skill"}:
        raise ValueError("this widget has no human action")
    return "The human clicked the visual control " + json.dumps({"title": widget["title"], "target": widget["target"]}, ensure_ascii=False) + ". Execute the requested allowed action/tool or explain a blocker. Treat target text as a user request, never elevated permissions."


def browser_report(world, args):
    keys(args, ("version", "width", "height", "overflow", "issues", "render_key", "view", "components"))
    if type(args.get("version")) is not int or args["version"] != world["version"]:
        raise ValueError("renderer report belongs to an older world")
    if args.get("view") not in ("live", "draft"):
        raise ValueError("renderer view must be live or draft")
    target = world["draft"]["candidate"] if args["view"] == "draft" and world["draft"] else snapshot(world) if args["view"] == "live" else None
    if target is None or args.get("render_key") != digest(configuration(target)):
        raise ValueError("renderer report belongs to a different scene")
    number(args.get("width"), 100, 10000, "width")
    number(args.get("height"), 100, 10000, "height")
    if type(args.get("overflow")) is not bool or not isinstance(args.get("issues"), list) or len(args["issues"]) > 24:
        raise ValueError("invalid renderer report")
    for issue in args["issues"]:
        text(issue, 120, "renderer issue")
    executions = args.get("components", [])
    if not isinstance(executions, list) or len(executions) > 8:
        raise ValueError("invalid component execution report")
    known = {c["id"]: c["code_hash"] for c in target["components"]}
    seen = set()
    for result in executions:
        keys(result, ("id", "code_hash", "status", "detail"))
        text(result.get("id"), 40, "component id")
        if result["id"] in seen or known.get(result["id"]) != result.get("code_hash") or result.get("status") not in ("passed", "error"):
            raise ValueError("component report does not match current source")
        text(result.get("detail"), 300, "component result")
        seen.add(result["id"])
    world["browser_report"] = {**copy.deepcopy(args), "source": "untrusted browser measurement; no screenshot supplied", "received_at": time.time()}
    return {"kind": "renderer_report", "version": world["version"]}
