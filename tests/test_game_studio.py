"""Self-passports, physical props, visual tools and atomic tested world releases."""
import copy
import json
from threading import Event, Timer
from uuid import uuid4

import pytest

from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import ToolExecutionContext, ToolRegistry
from dagi_core.web import WebApp
from game.bridge import register_game, render_game_context
from game.store import GameStore
from game.studio import activate, browser_report, build, digest, human_prompt, review, snapshot, visual_edit
from game.world import act, evolve, fresh_world, observation
from test_core_web import _config, _request, _start, _stop, _wait_for_status


def panel(id="panel", x=350):
    return {"operation": "widget", "widget": {"id": id, "kind": "panel", "x": x, "y": 65,
            "width": 240, "height": 100, "title": "My workbench", "body": "Actual state and measured feedback"}}


def begin_with_panel(world):
    build(world, {"operation": "begin", "objective": "Make my work visible"})
    build(world, {"operation": "edit", "changes": [panel()]})


def test_ladder_assists_real_climbing_and_fan_changes_measured_motion():
    empty, ladder = fresh_world(1), fresh_world(1)
    evolve(ladder, {"operation": "add", "object": {"id": "ladder", "kind": "ladder", "x": 180, "y": 200, "width": 35, "height": 340}})
    with pytest.raises(ValueError, match="contact"):
        act(empty, {"action": "climb_up", "frames": 60})
    assert empty["tick"] == 0
    act(ladder, {"action": "climb_up", "frames": 60})
    assert observation(ladder)["position"]["y"] < observation(empty)["position"]["y"] - 40
    assert observation(ladder)["activity"] == "climbing"
    assert observation(ladder)["contact"]["object_id"] == "ladder"
    off, on = fresh_world(1), fresh_world(1)
    for world, enabled in ((off, False), (on, True)):
        evolve(world, {"operation": "add", "object": {"id": "fan", "kind": "fan", "x": 80, "y": 440, "range": 300, "force": 1000, "angle": 0, "enabled": enabled}})
        act(world, {"action": "idle", "frames": 120})
    assert observation(on)["position"]["x"] > observation(off)["position"]["x"] + 40


def test_draft_report_measures_every_behavior_and_blocks_score_without_new_physics():
    world = fresh_world(1)
    evolve(world, {"operation": "behavior", "name": "pace", "steps": [{"action": "right", "frames": 20}, {"action": "left", "frames": 20}]})
    build(world, {"operation": "begin", "objective": "measurable improvement"})
    build(world, {"operation": "edit", "changes": [
        {"operation": "behavior", "name": "pace-two", "steps": [
            {"action": "right", "frames": 10}, {"action": "left", "frames": 10},
            {"action": "right", "frames": 10}, {"action": "left", "frames": 10}]}]})
    build(world, {"operation": "test"})
    report = world["draft"]["report"]
    assert {t["behavior"] for t in report["skill_tests"]} == {"pace", "pace-two"}
    assert report["improvement_checks"]["complexity_delta_source"] is False
    assert report["improvement_checks"]["interaction_verified"] is True
    assert report["improvement_checks"]["meaningful_displacement"] is False


def test_verified_ladder_climb_behavior_passes_interaction_and_displacement_checks():
    world = fresh_world(1)
    evolve(world, {"operation": "add", "object": {"id": "ladder", "kind": "ladder", "x": 180, "y": 200, "width": 35, "height": 340}})
    build(world, {"operation": "begin", "objective": "climb the ladder"})
    build(world, {"operation": "edit", "changes": [
        {"operation": "behavior", "name": "mount", "steps": [
            {"action": "right", "frames": 20}, {"action": "climb_up", "frames": 30}, {"action": "climb_down", "frames": 20}]}]})
    build(world, {"operation": "test"})
    report = world["draft"]["report"]
    trial = next(t for t in report["skill_tests"] if t["behavior"] == "mount")
    assert trial["refused"] is None
    assert trial["climbed_y"] > 10
    assert trial["contact_after"] == "ladder"
    assert report["improvement_checks"]["interaction_verified"] is True
    assert report["improvement_checks"]["complexity_delta_source"] is True
    assert report["improvement_checks"]["meaningful_displacement"] is True


def test_draft_is_invisible_to_live_physics_until_exact_passing_release(monkeypatch):
    world = fresh_world(1)
    before = snapshot(world)
    begin_with_panel(world)
    assert snapshot(world) == before
    build(world, {"operation": "test"})
    assert world["draft"]["report"]["passed"] is True
    assert snapshot(world) == before
    build(world, {"operation": "commit"})
    release_id = world["draft"]["id"]
    with pytest.raises(ValueError, match="countdown"):
        activate(world, {"id": release_id})
    assert world["widgets"] == []
    deadline = world["draft"]["activate_at"]
    monkeypatch.setattr("game.studio.time.time", lambda: deadline + .1)
    activate(world, {"id": release_id})
    assert world["version"] == 1 and world["draft"] is None
    assert world["widgets"][0]["id"] == "panel"
    assert world["previous"] == before
    assert world["last_release"]["id"] == release_id


@pytest.mark.parametrize("change,check", [
    ({"operation": "controller", "values": {"balance": 0}}, "posture_no_regression"),
    ({"operation": "theme", "values": {"background": "#282d23"}}, "layout_readable"),
    (panel("overlap", 360), "layout_readable"),
])
def test_regressions_and_unreadable_layout_cannot_be_released(change, check):
    world = fresh_world(1)
    begin_with_panel(world)
    build(world, {"operation": "edit", "changes": [change]})
    build(world, {"operation": "test"})
    assert world["draft"]["report"]["checks"][check] is False
    with pytest.raises(ValueError, match="passing"):
        build(world, {"operation": "commit"})
    assert world["version"] == 0 and world["widgets"] == []


def test_edit_after_test_invalidates_evidence_and_test_budget_is_bounded():
    world = fresh_world(1)
    begin_with_panel(world)
    build(world, {"operation": "test"})
    build(world, {"operation": "edit", "changes": [{"operation": "controller", "values": {"speed": 100}}]})
    with pytest.raises(ValueError, match="passing"):
        build(world, {"operation": "commit"})
    for _ in range(2):
        build(world, {"operation": "test"})
    with pytest.raises(ValueError, match="three"):
        build(world, {"operation": "test"})


def test_stale_live_world_or_tampered_candidate_cannot_reuse_a_test():
    world = fresh_world(1)
    begin_with_panel(world)
    build(world, {"operation": "test"})
    world["draft"]["candidate"]["controller"]["balance"] = 0
    with pytest.raises(ValueError, match="stale"):
        build(world, {"operation": "commit"})
    build(world, {"operation": "discard"})
    begin_with_panel(world)
    act(world, {"action": "right", "frames": 1})
    with pytest.raises(ValueError, match="live world changed"):
        build(world, {"operation": "test"})


def test_old_world_migrates_without_reset_and_failed_batch_is_atomic(tmp_path):
    state = StateStore(tmp_path / "state.db")
    session = state.create_session()
    with GameStore(state.path) as store:
        old = store.create(session)
        for field in ("widgets", "theme", "version", "draft", "last_release", "previous", "browser_report"):
            old.pop(field)
        old["schema_version"] = 1
        store.db.execute("UPDATE game_worlds SET world_json=?", (json.dumps(old),))
        store.db.commit()
        migrated = store.get(session)
        assert migrated["nodes"] == old["nodes"] and migrated["widgets"] == []
        store.apply(session, build, {"operation": "begin", "objective": "atomic experiment"})
        before = store.get(session)
        with pytest.raises(ValueError):
            store.apply(session, build, {"operation": "edit", "changes": [panel(), {"operation": "theme", "values": {"background": "javascript:bad"}}]})
        assert store.get(session) == before
    state.close()


def test_interrupted_release_keeps_live_world_and_allows_explicit_inspection(tmp_path):
    state = StateStore(tmp_path / "state.db")
    session = state.create_session()
    with GameStore(state.path) as store:
        store.create(session)
        for args in ({"operation": "begin", "objective": "inspect recovery"}, {"operation": "edit", "changes": [panel()]}, {"operation": "test"}, {"operation": "commit"}):
            store.apply(session, build, args)
        store.recover_releases()
        recovered = store.get(session)
        assert recovered["version"] == 0 and recovered["widgets"] == []
        assert recovered["draft"]["state"] == "tested"
        assert "interrupted" in recovered["draft"]["release_error"]
    state.close()


def test_renderer_reports_and_clicks_are_bound_to_current_declared_scene():
    world = fresh_world(1)
    visual_edit(world, {"operation": "widget", "widget": {"id": "walk", "kind": "button", "x": 650, "y": 70, "width": 220, "height": 65,
        "title": "Walk right", "target": {"type": "action", "action": "right", "frames": 30}}})
    assert '"action": "right"' in human_prompt(world, {"widget_id": "walk", "version": 0})
    with pytest.raises(ValueError, match="world changed"):
        human_prompt(world, {"widget_id": "walk", "version": 1})
    report = {"version": 0, "view": "live", "render_key": digest(snapshot(world)), "width": 1280, "height": 800, "overflow": False, "issues": []}
    browser_report(world, report)
    assert review(world)["browser"]["stale"] is False
    act(world, {"action": "right", "frames": 30})
    assert review(world)["browser"]["stale"] is True
    with pytest.raises(ValueError, match="different scene"):
        browser_report(world, report)


def test_passport_is_current_and_live_actions_are_blocked_during_a_draft(tmp_path):
    state = StateStore(tmp_path / "state.db")
    session = state.create_session()
    with GameStore(state.path) as store:
        store.create(session)
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    register_game(tools)
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "brain-model"))
    initial = render_game_context(state.path, session, tools.workspace, "brain-model")
    assert "LLM API JSON request" in initial and f"stickman:{session}" in initial
    assert tools.call("game_build", {"operation": "begin", "objective": "visible work"}).is_error is False
    assert '"state":"building"' in render_game_context(state.path, session, tools.workspace, "brain-model")
    assert tools.call("game_act", {"action": "right"}).is_error is True
    assert tools.call("game_goal", {"x": 900}).is_error is True
    assert tools.call("game_visual", panel()).is_error is False
    with GameStore(state.path) as store:
        world = store.get(session)
        assert world["widgets"] == [] and len(world["draft"]["candidate"]["widgets"]) == 1
    state.close()


def test_cancelling_release_during_countdown_never_installs_the_candidate(tmp_path):
    state = StateStore(tmp_path / "state.db")
    session = state.create_session()
    with GameStore(state.path) as store:
        store.create(session)
        for args in ({"operation": "begin", "objective": "cancel experiment"}, {"operation": "edit", "changes": [panel()]}, {"operation": "test"}):
            store.apply(session, build, args)
    tools = ToolRegistry(tmp_path / "workspace", state, session)
    register_game(tools)
    cancel = Event()
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "fake", cancel))
    timer = Timer(.12, cancel.set)
    timer.start()
    try:
        result = tools.call("game_build", {"operation": "commit"})
        assert result.is_error is True and "cancelled" in result.content
        with GameStore(state.path) as store:
            world = store.get(session)
            assert world["widgets"] == [] and world["version"] == 0
            assert world["draft"]["state"] == "tested"
    finally:
        timer.join()
        state.close()


def upgrade_commands():
    return [
        ("game_inspect", {"view": "catalog"}),
        ("game_build", {"operation": "begin", "objective": "Progress my physical walking skill"}),
        ("game_build", {"operation": "edit", "changes": [
            {"operation": "behavior", "name": "walk", "steps": [
                {"action": "right", "frames": 60}, {"action": "idle", "frames": 15},
            ]},
            {"operation": "widget", "widget": {"id": "walk-skill", "kind": "skill", "x": 30, "y": 65, "width": 250, "height": 100,
             "title": "Walking skill", "body": "Saved physical program", "target": {"type": "behavior", "name": "walk"}}},
            {"operation": "widget", "widget": {"id": "walk-button", "kind": "button", "x": 320, "y": 65, "width": 220, "height": 80,
             "title": "Perform walk", "target": {"type": "behavior", "name": "walk"}}},
        ]}),
        ("game_review", {}), ("game_build", {"operation": "test"}), ("game_build", {"operation": "commit"}),
    ]


class StudioProvider:
    model = "main-model"

    def __init__(self, instances):
        self.requests = []
        self.commands = upgrade_commands()
        self.prefix = uuid4().hex
        instances.append(self)

    def stream(self, messages, tools):
        if not tools:
            yield StreamEvent(kind="text", text="Prior world experiments are saved. Inspect the current world and tool outcomes before acting.")
            yield StreamEvent(kind="finish", finish_reason="stop")
            return
        self.requests.append(copy.deepcopy(messages))
        index = len(self.requests) - 1
        if index < len(self.commands):
            name, args = self.commands[index]
            yield StreamEvent(kind="tool_call", tool_call={"id": f"{self.prefix}-{index}", "name": name, "arguments": args})
            yield StreamEvent(kind="finish", finish_reason="tool_calls")
        else:
            yield StreamEvent(kind="text", text="World upgrade applied; physical health and layout checks passed.")
            yield StreamEvent(kind="finish", finish_reason="stop")


class InteractiveStudioProvider(StudioProvider):
    def stream(self, messages, tools):
        if not self.requests:
            user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
            if user.startswith("The human clicked"):
                payload, _ = json.JSONDecoder().raw_decode(user[user.index("{"):])
                if "todo item" in user:
                    self.commands = [("game_visual", payload)]
                else:
                    target = payload["target"]
                    if target["type"] == "action":
                        self.commands = [("game_act", {k: v for k, v in target.items() if k != "type"})]
                    elif target["type"] == "behavior":
                        self.commands = [("game_act", {"action": "behavior", "name": target["name"]})]
        yield from super().stream(messages, tools)


def test_web_self_improvement_injects_passport_before_first_call_and_releases_verified_world(tmp_path):
    instances = []
    app = WebApp(_config(tmp_path), provider_factory=lambda *_: InteractiveStudioProvider(instances))
    server, thread, base = _start(app)
    try:
        _, _, body = _request(base + "/api/game/sessions", "POST", {"title": "self-improvement"})
        session = json.loads(body)["session_id"]
        _, _, body = _request(f"{base}/api/sessions/{session}/runs", "POST", {"message": "Improve yourself"})
        run = json.loads(body)["run_id"]
        detail = _wait_for_status(base, run, "completed")
        assert all(c["status"] == "succeeded" for c in detail["tool_calls"])
        provider = next(p for p in instances if p.requests)
        first = next(m["content"] for m in provider.requests[0] if m["role"] == "system")
        assert "DAGI_SELF_PASSPORT_JSON_BEGIN" in first and f"stickman:{session}" in first
        assert any('"version":1' in m["content"] for m in provider.requests[-1] if m["role"] == "system")
        _, _, body = _request(f"{base}/api/game/sessions/{session}")
        data = json.loads(body)
        assert data["scene"]["version"] == 1 and data["build"] is None
        assert data["scene"]["tick"] == 150  # The released physical skill ran for two autonomous cycles.
        assert len(data["motion"]) > 1  # The viewer can replay measured physical frames.
        execution = data["scene"]["autonomy_execution"]
        assert execution["program"] == "walk" and execution["status"] == "completed"
        assert execution["cycles_completed"] == 2 and execution["frames_executed"] == 150
        assert {w["kind"] for w in data["widgets"]} == {"skill", "button"}
        assert data["scene"]["objects"] == []
        assert all(data["last_release"]["checks"].values())
        _, _, body = _request(f"{base}/api/game/sessions/{session}/interact", "POST", {"widget_id": "walk-button", "version": 1})
        clicked = json.loads(body)["run_id"]
        _wait_for_status(base, clicked, "completed")
        _, _, body = _request(f"{base}/api/game/sessions/{session}")
        assert json.loads(body)["scene"]["tick"] == 225
    finally:
        _stop(server, thread)
