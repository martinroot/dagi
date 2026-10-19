"""Feedback execution, real rollout evidence and bounded autonomous turns."""
from copy import deepcopy
from contextlib import closing
import json
import time

import pytest

from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.web import WebApp
from game.living import advance, design, evaluate, trial
from game.store import GameStore
from game.studio import activate, build
from game.world import fresh_world
from test_core_web import _config, _request, _start, _stop


def policy(world, code, name="invented"):
    design(world, {"operation": "policy", "name": name, "code": code, "description": "A test-authored feedback controller"})


@pytest.mark.parametrize("source", [
    "__import__('os').system('id')", "s.__class__", "[x for x in s]",
    "open('/etc/passwd')", "(lambda: 1)()", "2**1000000000",
    "'x'*1000000000", "{'x': sqrt(-1)}", "{'x': 1/0}",
])
def test_policy_language_rejects_host_access_and_unbounded_work(source):
    with pytest.raises(ValueError):
        evaluate(source, {"s": {}, "m": {}})


def test_feedback_uses_current_pose_and_persistent_memory_instead_of_a_fixed_action_list():
    world = fresh_world(1)
    policy(world, "{'drive': clamp((350-s['x'])/50,-1,1), 'memory': {'ticks': get(m,'ticks',0)+1}, 'intent': 'Testing feedback'}")
    advance(world, 600)
    assert abs(world["nodes"]["hip"]["x"] - 350) < 15
    assert world["policy_state"]["ticks"] == 600
    assert world["life"]["intent"] == "Testing feedback"
    # The same program reverses on a new observation, no model call/rewrite.
    for p in world["nodes"].values():
        p["x"] += 150
        p["px"] += 150
    before = world["nodes"]["hip"]["x"]
    advance(world, 180)
    assert world["nodes"]["hip"]["x"] < before - 50


def test_policy_can_change_pose_and_apply_joint_and_object_forces():
    world = fresh_world(1)
    design(world, {"operation": "body", "body": {"id": "round", "shape": "circle", "x": 650, "y": 450, "radius": 18}})
    policy(world, "{'pose': {'left_hand': [-65,-45+15*sin(s['t']*4)]}, 'forces': {'right_hand':[100,-100]}, 'object_forces': {'round':[800,-200]}}")
    advance(world, 120)
    assert world["objects"][0]["x"] > 700
    assert world["nodes"]["left_hand"]["x"] < world["nodes"]["hip"]["x"] - 30


def test_physical_object_is_pushed_by_body_contact_without_a_named_interaction():
    world = fresh_world(1)
    design(world, {"operation": "body", "body": {"id": "load", "shape": "rect", "x": 245, "y": 505, "width": 30, "height": 65, "mass": .5}})
    policy(world, "{'drive': 1}")
    advance(world, 200)
    assert world["objects"][0]["x"] > 255
    assert world["objects"][0]["vx"] != 0


def test_trial_runs_real_source_and_does_not_move_live_world_or_mutate_memory():
    world = fresh_world(1)
    policy(world, "{'drive': 1, 'memory': {'n': get(m,'n',0)+1}}")
    before = deepcopy(world)
    result = trial(world)
    assert result["passed"] and result["dx"] > 100
    assert world == before


def test_material_changes_have_measured_physical_effects():
    a = fresh_world(1)
    policy(a, "{'drive': .6, 'pose': {'left_hand': [-50,-60+20*sin(s['t']*4)]}}")
    b = deepcopy(a)
    design(b, {"operation": "material", "values": {"damping": .94, "pose_strength": .16}})
    baseline, candidate = trial(a), trial(b)
    assert baseline["passed"] and candidate["passed"]
    assert baseline["dx"] != candidate["dx"]
    assert baseline["speed_jitter"] != candidate["speed_jitter"]
    assert "max_bone_error" in candidate and "mean_foot_slip" in candidate


def test_delayed_policy_failure_blocks_release_even_without_any_skill_widget():
    world = fresh_world(1)
    build(world, {"operation": "begin", "objective": "Try a new controller"})
    build(world, {"operation": "edit", "changes": [{"operation": "policy", "name": "bad", "description": "Fails on a later tick", "code": "{'drive': 0 if s['t']<1 else 1/0}"}]})
    build(world, {"operation": "test"})
    report = world["draft"]["report"]
    assert report["passed"] is False
    assert report["feedback_trial"]["candidate"]["passed"] is False
    assert "policy runtime" in report["feedback_trial"]["candidate"]["error"]
    assert world["tick"] == 0 and not world["widgets"]
    with pytest.raises(ValueError, match="passing"):
        build(world, {"operation": "commit"})


def test_simpler_policy_can_replace_complex_policy_and_appearance_does_not_fake_motion():
    world = fresh_world(1)
    policy(world, "{'drive': sin(s['t'])*0.1, 'memory': {'n': get(m,'n',0)+1}}")
    build(world, {"operation": "begin", "objective": "Simplify and clarify"})
    build(world, {"operation": "edit", "changes": [
        {"operation": "policy", "name": "invented", "description": "A simpler controller", "code": "{'drive': 0.2}"},
        {"operation": "appearance", "values": {"stroke": "#203a55", "head_radius": 15, "trail": 4}},
    ]})
    build(world, {"operation": "test"})
    assert world["draft"]["report"]["passed"]
    build(world, {"operation": "commit"})
    world["draft"]["activate_at"] = 0
    activate(world, {"id": world["draft"]["id"]})
    assert world["version"] == 1 and world["appearance"]["head_radius"] == 15
    assert world["evolution"][0]["trial"]["candidate"]["frames"] == 240
    a, b = deepcopy(world), deepcopy(world)
    design(b, {"operation": "appearance", "values": {"head_radius": 8, "line_width": 2}})
    advance(a, 30)
    advance(b, 30)
    assert a["nodes"] == b["nodes"]


class LivingProvider:
    """Scripted brain checks orchestration, not the quality of an external LLM."""
    def __init__(self):
        self.calls = 0

    def stream(self, messages, tools):
        self.calls += 1
        steps = [
            ("game_build", {"operation": "begin", "objective": "An invented continuous activity"}),
            ("game_design", {"operation": "policy", "name": "self-authored", "description": "Closed loop exploration", "code": "{'drive': 0.4 if s['x']<650 else -0.4, 'memory': {'steps':get(m,'steps',0)+1}, 'intent':'Exploring my world'}"}),
            ("game_build", {"operation": "test"}),
            ("game_build", {"operation": "commit"}),
        ]
        if self.calls <= len(steps):
            name, args = steps[self.calls - 1]
            yield StreamEvent("tool_call", tool_call={"id": f"living-{self.calls}", "name": name, "arguments": args})
        else:
            yield StreamEvent("text", text="Published tested feedback code.")
        yield StreamEvent("finish", finish_reason="tool_calls" if self.calls <= len(steps) else "stop")


def wait_until(check, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(.03)
    raise AssertionError("condition did not become true")


def test_autonomous_iteration_publishes_code_then_body_continues_without_more_api_calls(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_: LivingProvider())
    server, thread, base = _start(app)
    try:
        _, _, data = _request(base + "/api/game/sessions", "POST", {"title": "living", "mode":"assisted"})
        session = json.loads(data)["session_id"]
        _request(f"{base}/api/game/sessions/{session}/life", "POST", {"action": "start", "iterations": 1})

        def read():
            with GameStore(app.config.database) as store:
                return store.get(session)

        world = wait_until(lambda: (w if w["version"] == 1 and w["policy_state"].get("steps", 0) >= 12 and not w["life"]["thinking"] else None) if (w := read()) else None)
        assert world["life"]["iteration"] == 1
        tick = world["tick"]
        x = world["nodes"]["hip"]["x"]
        later = wait_until(lambda: w if (w := read())["tick"] >= tick + 30 else None)
        assert later["nodes"]["hip"]["x"] > x
        with closing(StateStore(app.config.database)) as state:
            runs = state.list_runs(session, 10)
            assert len(runs) == 1
            assert len(state.list_provider_calls(runs[0]["run_id"])) == 5
        _request(f"{base}/api/game/sessions/{session}/life", "POST", {"action": "pause"})
        paused = read()
        time.sleep(.2)
        assert read()["tick"] == paused["tick"]
        _request(f"{base}/api/game/sessions/{session}/life", "POST", {"action": "play"})
        wait_until(lambda: read()["tick"] > paused["tick"])
        with closing(StateStore(app.config.database)) as state:
            assert len(state.list_runs(session, 10)) == 1
    finally:
        _stop(server, thread)


def test_restart_preserves_policy_and_memory_but_does_not_restart_clock_or_spend_budget(tmp_path):
    app = WebApp(_config(tmp_path), provider_factory=lambda *_: LivingProvider())
    server, thread, base = _start(app)
    try:
        _, _, data = _request(base + "/api/game/sessions", "POST", {"title": "restart", "mode":"assisted"})
        session = json.loads(data)["session_id"]
        with GameStore(app.config.database) as store:
            with store.mutation(session) as w:
                policy(w, "{'drive': 0.2, 'memory': {'n': get(m,'n',0)+1}}")
        _request(f"{base}/api/game/sessions/{session}/life", "POST", {"action": "play"})
        time.sleep(.25)
    finally:
        _stop(server, thread)

    other = WebApp(_config(tmp_path), provider_factory=lambda *_: LivingProvider())
    server, thread, base = _start(other)
    try:
        with GameStore(other.config.database) as store:
            world = store.get(session)
        assert not world["life"]["running"]
        assert world["policy_state"]["n"] > 0
        assert world["active_policy"] == "invented"
        with closing(StateStore(other.config.database)) as state:
            assert not state.list_runs(session, 10)
    finally:
        _stop(server, thread)


def test_model_iterations_continue_without_human_messages_and_stop_at_selected_count(tmp_path):
    class QuietProvider:
        def stream(self, messages, tools):
            yield StreamEvent("text", text="An observed development attempt; no claimed improvement.")
            yield StreamEvent("finish", finish_reason="stop")

    app = WebApp(_config(tmp_path), provider_factory=lambda *_: QuietProvider())
    server, thread, base = _start(app)
    try:
        _, _, data = _request(base + "/api/game/sessions", "POST", {"title": "independent turns"})
        session = json.loads(data)["session_id"]
        _request(f"{base}/api/game/sessions/{session}/life", "POST", {"action": "start", "iterations": 2})

        def read():
            with GameStore(app.config.database) as store:
                return store.get(session)["life"]

        wait_until(lambda: (v := read())["iteration"] == 1 and not v["thinking"])
        app.life._next_thought[session] = 0  # Advance the deliberation timer, not the brain itself.
        wait_until(lambda: (v := read())["iteration"] == 2 and not v["thinking"])
        app.life._next_thought[session] = 0
        time.sleep(.25)
        with closing(StateStore(app.config.database)) as state:
            assert len(state.list_runs(session, 10)) == 2
    finally:
        _stop(server, thread)
