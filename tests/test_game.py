"""Physical, persistence and real agent/web integration checks; no model API calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import math
from urllib.error import HTTPError

import pytest

from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.tools import ToolExecutionContext, ToolRegistry
from dagi_core.web import WebApp
from game.bridge import GAME_PROMPT, program_identity, register_game
from game.store import GameStore
from game.world import LINKS, act, evolve, fresh_world, observation, reflect, set_goal
from test_core_web import _config, _request, _start, _stop, _wait_for_status


def test_motor_keeps_body_upright_but_disabling_it_allows_a_physical_fall():
    assisted, ragdoll = fresh_world(1), fresh_world(1)
    evolve(ragdoll, {"operation": "controller", "values": {"balance": 0}})
    act(assisted, {"action": "idle", "frames": 180})
    act(ragdoll, {"action": "idle", "frames": 180})
    assert observation(assisted)["upright"] is True
    assert observation(ragdoll)["upright"] is False
    assert ragdoll["nodes"]["hip"]["y"] > assisted["nodes"]["hip"]["y"] + 40


def test_actions_are_deterministic_bounded_and_produce_grounded_goal_evidence():
    a, b = fresh_world(7), fresh_world(7)
    for world in (a, b):
        set_goal(world, {"x": 280, "tolerance": 25})
        act(world, {"action": "right", "frames": 120})
    assert a == b
    observed = observation(a)
    assert observed["position"]["x"] > 260
    assert observed["goal"]["passed"] is True
    assert observed["tick"] == 120
    assert len(a["motion"]) > 2
    for name, p in a["nodes"].items():
        assert all(math.isfinite(value) for value in p.values())
        assert p["y"] <= 540 - (12 if name == "head" else 4)
    for left, right, length in LINKS:
        p, q = a["nodes"][left], a["nodes"][right]
        assert abs(math.hypot(p["x"] - q["x"], p["y"] - q["y"]) - length) < 2


def test_goal_observation_exposes_signed_error_and_direction_to_recover_overshoot():
    world = fresh_world(1)
    start_x = observation(world)["position"]["x"]

    set_goal(world, {"x": start_x + 30, "tolerance": 5})
    rightward = observation(world)["goal"]
    assert rightward["signed_error"] == 30
    assert rightward["direction_to_goal"] == "right"

    set_goal(world, {"x": start_x - 30, "tolerance": 5})
    overshot = observation(world)["goal"]
    assert overshot["signed_error"] == -30
    assert overshot["direction_to_goal"] == "left"


def test_avatar_state_is_derived_from_persisted_experiment_outcomes():
    world = fresh_world(1)
    assert observation(world)["avatar_state"] == "resting"
    world["reflections"] = [{"expected": "progress", "hypothesis": "test", "next_test": "observe"}]
    assert observation(world)["avatar_state"] == "curious"
    world["autonomy_execution"] = {"status": "running"}
    assert observation(world)["avatar_state"] == "focused"
    world["autonomy_execution"] = {"status": "goal_passed"}
    assert observation(world)["avatar_state"] == "satisfied"
    world["autonomy_execution"] = {"status": "completed", "goal_distance_change": 2.0}
    assert observation(world)["avatar_state"] == "uncertain"


def test_saved_skill_complexity_is_measurable_and_versioned():
    steps = [
        {"action": "right", "frames": 12},
        {"action": "jump", "frames": 6},
        {"action": "left", "frames": 8},
    ]
    program = program_identity({"behaviors": {"dance": steps}})[0]
    assert program["name"] == "dance"
    assert len(program["version"]) == 12
    assert program["steps"] == 3
    assert program["unique_actions"] == 3
    assert program["complexity_score"] > program["steps"]
    single = [{"action": "right", "frames": 12}]
    padded = single * 3
    assert program_identity({"behaviors": {"single": single}})[0]["complexity_score"] == \
        program_identity({"behaviors": {"padded": padded}})[0]["complexity_score"]


def test_jump_has_measured_airtime_and_wall_blocks_horizontal_progress():
    world = fresh_world(1)
    act(world, {"action": "jump", "frames": 15})
    assert observation(world)["position"]["y"] < 435
    assert observation(world)["grounded"] is False
    act(world, {"action": "idle", "frames": 180})
    assert observation(world)["grounded"] is True
    evolve(world, {"operation": "add", "object": {"id": "wall", "kind": "block", "x": 280, "y": 240, "width": 40, "height": 300}})
    for _ in range(3):
        act(world, {"action": "right", "frames": 240})
    assert observation(world)["position"]["x"] < 280


def test_behavior_executes_changed_program_and_reflection_attaches_actual_evidence():
    world = fresh_world(1)
    evolve(world, {"operation": "behavior", "name": "advance", "steps": [{"action": "right", "frames": 120}, {"action": "idle", "frames": 30}]})
    act(world, {"action": "behavior", "name": "advance"})
    reflect(world, {"expected": "advance 100", "hypothesis": "motor needs calibration", "next_test": "use a longer stride"})
    record = world["reflections"][-1]
    assert record["evidence_tick"] == 150
    assert record["observed"]["position"]["x"] == observation(world)["position"]["x"]
    assert record["status"].startswith("hypothesis")


def test_game_act_ignores_empty_name_on_simple_action_and_reports_normalization():
    world = fresh_world(1)

    result = act(world, {"action": "right", "frames": 30, "name": ""})

    assert world["tick"] == 30
    assert result["command"] == {"action": "right", "frames": 30}
    assert result["ignored_arguments"] == ["name"]
    assert result["duration_source"] == "frames"


def test_game_act_behavior_duration_comes_from_saved_steps_not_frames_hint():
    world = fresh_world(1)
    evolve(world, {"operation": "behavior", "name": "short-walk", "steps": [
        {"action": "right", "frames": 18}, {"action": "idle", "frames": 12},
    ]})

    result = act(world, {"action": "behavior", "name": "short-walk", "frames": 20})

    assert world["tick"] == 30
    assert result["command"] == {"action": "behavior", "name": "short-walk"}
    assert result["ignored_arguments"] == ["frames"]
    assert result["duration_source"] == "saved behavior steps"


@pytest.fixture
def stored_world(tmp_path):
    state = StateStore(tmp_path / "state.db")
    session = state.create_session(workspace="game/test")
    with GameStore(state.path) as store:
        store.create(session)
    yield state, session
    state.close()


@pytest.mark.parametrize("operation,args", [
    (act, {"action": []}), (act, {"action": "right", "frames": 241}),
    (act, {"action": "idle", "frames": True}),
    (evolve, {"operation": []}),
    (evolve, {"operation": "controller", "values": {"speed": float("nan")}}),
    (evolve, {"operation": "controller", "values": {"speed": 100, "balance": 2}}),
    (evolve, {"operation": "add", "object": {"id": "bad", "kind": "block", "x": 170, "y": 400, "width": 50, "height": 100}}),
    (evolve, {"operation": "behavior", "name": "loop", "steps": [{"action": "behavior", "name": "loop"}]}),
    (evolve, {"operation": "add", "object": {"id": "marker", "kind": "marker", "x": 10, "y": 10, "width": {"unused": "payload"}}}),
    (evolve, {"operation": "behavior", "name": "payload", "steps": [{"action": "idle", "name": {"unused": "payload"}}]}),
])
def test_invalid_edits_rollback_without_advancing_revision(stored_world, operation, args):
    state, session = stored_world
    with GameStore(state.path) as store:
        before = store.get(session)
        with pytest.raises(ValueError):
            store.apply(session, operation, args)
        assert store.get(session) == before


def test_cancelled_simulation_rolls_back_every_partial_tick(stored_world):
    state, session = stored_world
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 5

    with GameStore(state.path) as store:
        before = store.get(session)
        with pytest.raises(ValueError, match="cancelled"):
            store.apply(session, act, {"action": "right", "frames": 120}, cancelled=cancelled)
        assert store.get(session) == before


def test_parallel_writers_serialize_and_readers_do_not_advance_time(stored_world):
    state, session = stored_world

    def advance(_):
        with GameStore(state.path) as store:
            store.apply(session, act, {"action": "idle", "frames": 30})

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(advance, range(3)))
    with GameStore(state.path) as store:
        a, b = store.get(session), store.get(session)
    assert a == b
    assert a["tick"] == 90 and a["revision"] == 3


def test_tools_are_scoped_correctable_and_do_not_claim_retryable_actions(stored_world, tmp_path):
    state, session = stored_world
    ordinary = state.create_session()
    tools = ToolRegistry(tmp_path / "body", state, session)
    assert register_game(tools) is True
    assert register_game(ToolRegistry(tmp_path / "other", state, ordinary)) is False
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "fake"))
    actual = json.loads(tools.call("game_inspect", {}).content)
    assert actual["self"]["body_id"] == f"stickman:{session}"
    assert actual["self"]["workspace"] == str(tools.workspace)
    assert tools.call("game_act", {"action": []}).is_error is True
    assert tools.call("game_act", {"action": "right", "session_id": ordinary}).is_error is True
    assert tools.recovery_metadata("game_act")["retryable"] is False
    assert tools.call("game_inspect", {"view": "source", "path": "../../.env"}).is_error is True
    assert '"source":' in tools.call("game_inspect", {"view": "source", "path": "game/world.py"}).content
    with GameStore(state.path) as store:
        assert store.get(session)["tick"] == 0


def test_game_inspect_accepts_unique_source_basename_and_rejects_ambiguous_or_unsafe_paths(stored_world, tmp_path, monkeypatch):
    from game import bridge

    state, session = stored_world
    monkeypatch.setitem(bridge.SOURCE_FILES, "other/index.html", bridge.SOURCE_FILES["game/static/index.html"])
    tools = ToolRegistry(tmp_path / "source-inspection", state, session)
    register_game(tools)
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "fake"))

    component = tools.call("game_inspect", {"view": "source", "path": "component-host.js"})
    assert component.is_error is False
    result = json.loads(component.content)
    assert result["path"] == "game/static/component-host.js"
    assert "workerBootstrap" in result["source"]

    ambiguous = tools.call("game_inspect", {"view": "source", "path": "index.html"})
    assert ambiguous.is_error is True
    assert "game/static/index.html" in ambiguous.content
    assert "other/index.html" in ambiguous.content
    assert tools.call("game_inspect", {"view": "source", "path": "../../.env"}).is_error is True


def test_game_act_reports_signed_goal_progress_for_wrong_direction(stored_world, tmp_path):
    state, session = stored_world
    with GameStore(state.path) as store:
        world = store.get(session)
        start_x = world["nodes"]["hip"]["x"]
        store.apply(session, set_goal, {"x": start_x - 30, "tolerance": 5})
    tools = ToolRegistry(tmp_path / "goal-progress", state, session)
    register_game(tools)
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "fake"))

    result = tools.call("game_act", {"action": "right", "frames": 10})
    assert result.is_error is False
    payload = json.loads(result.content)
    assert payload["goal"]["direction_to_goal"] == "left"
    assert payload["goal_progress"]["distance_change"] > 0
    assert payload["goal_progress"]["improved"] is False
    assert payload["goal_progress"]["signed_error"] < 0


def test_game_act_runs_saved_behavior_cycles_without_provider_calls(stored_world, tmp_path):
    state, session = stored_world
    with GameStore(state.path) as store:
        store.apply(session, evolve, {"operation": "behavior", "name": "pace", "steps": [
            {"action": "right", "frames": 3}, {"action": "left", "frames": 3},
        ]})
    tools = ToolRegistry(tmp_path / "autonomous-program", state, session)
    register_game(tools)
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "fake"))

    result = tools.call("game_act", {"action": "behavior", "name": "pace", "cycles": 4})
    assert result.is_error is False
    payload = json.loads(result.content)
    assert payload["program_execution"]["program"] == "pace"
    assert payload["program_execution"]["cycles_requested"] == 4
    assert payload["program_execution"]["cycles_completed"] == 4
    assert payload["program_execution"]["frames_executed"] == 24
    assert payload["autonomy_execution"]["status"] == "completed"
    with GameStore(state.path) as store:
        saved = store.get(session)
    assert saved["tick"] == 24
    assert saved["autonomy_execution"]["program"] == "pace"
    assert any(item.get("kind") == "autonomy_execution" for item in saved["history"])


def test_self_improve_draft_rejects_dashboard_only_commit(stored_world, tmp_path):
    state, session = stored_world
    state.append_message(session, {"role": "user", "content": "Улучши себя как физического персонажа"})
    tools = ToolRegistry(tmp_path / "self-improve-guard", state, session)
    register_game(tools)
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "fake"))

    simple_move = tools.call("game_act", {"action": "right", "frames": 30})
    assert simple_move.is_error is True
    assert "saved behavior" in simple_move.content
    assert tools.call("game_build", {"operation": "begin", "objective": "Add a dashboard"}).is_error is False
    visual = {"operation": "widget", "widget": {
        "id": "only-panel", "kind": "panel", "x": 20, "y": 60,
        "width": 180, "height": 80, "title": "Telemetry", "body": "Chart only",
    }}
    assert tools.call("game_build", {"operation": "edit", "changes": [visual]}).is_error is False
    assert tools.call("game_build", {"operation": "test"}).is_error is False

    rejected = tools.call("game_build", {"operation": "commit"})
    assert rejected.is_error is True
    assert "physical skill complexity" in rejected.content
    with GameStore(state.path) as store:
        saved = store.get(session)
    assert saved["version"] == 0
    assert saved["widgets"] == []
    assert saved["draft"]["state"] == "tested"


def test_autonomous_behavior_stops_inside_goal_tolerance_before_overshooting(stored_world, tmp_path):
    state, session = stored_world
    with GameStore(state.path) as store:
        world = store.get(session)
        start_x = world["nodes"]["hip"]["x"]
        store.apply(session, set_goal, {"x": start_x + 30, "tolerance": 5})
        store.apply(session, evolve, {"operation": "behavior", "name": "approach", "steps": [
            {"action": "right", "frames": 60},
        ]})
    tools = ToolRegistry(tmp_path / "goal-stop", state, session)
    register_game(tools)
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "fake"))

    result = tools.call("game_act", {"action": "behavior", "name": "approach", "cycles": 5})
    assert result.is_error is False
    payload = json.loads(result.content)
    assert payload["goal"]["passed"] is True
    assert payload["program_execution"]["status"] == "goal_passed"
    assert payload["program_execution"]["stop_reason"] == "goal_passed"
    assert payload["program_execution"]["frames_executed"] < 60
    assert payload["program_execution"]["cycles_completed"] == 0
    assert payload["program_execution"]["cycles_requested"] == 5


def test_dance_program_runs_multiple_cycles_and_frame_ceiling_is_enforced(stored_world, tmp_path):
    state, session = stored_world
    with GameStore(state.path) as store:
        store.apply(session, evolve, {"operation": "behavior", "name": "dance", "steps": [
            {"action": "jump", "frames": 4}, {"action": "left", "frames": 4},
            {"action": "right", "frames": 4}, {"action": "idle", "frames": 4},
        ]})
        store.apply(session, evolve, {"operation": "behavior", "name": "long-program", "steps": [
            {"action": "left", "frames": 240}, {"action": "right", "frames": 240},
            {"action": "left", "frames": 240}, {"action": "right", "frames": 240},
        ]})
    tools = ToolRegistry(tmp_path / "dance-program", state, session)
    register_game(tools)
    tools.set_execution_context(ToolExecutionContext(session, "run", 0, "fake"))

    dance = tools.call("game_act", {"action": "behavior", "name": "dance", "cycles": 2})
    assert dance.is_error is False
    dance_payload = json.loads(dance.content)
    assert dance_payload["program_execution"]["cycles_completed"] == 2
    assert dance_payload["program_execution"]["frames_executed"] == 32
    before_rejected_run = dance_payload["tick"]
    too_long = tools.call("game_act", {"action": "behavior", "name": "long-program", "cycles": 10})
    assert too_long.is_error is True
    assert "2400 frames" in too_long.content
    with GameStore(state.path) as store:
        after = store.get(session)
    assert after["tick"] == before_rejected_run
    assert after["autonomy_execution"]["program"] == "dance"


def test_studio_prompt_uses_canonical_paths_and_explains_autonomous_goal_and_draft_rules():
    assert "game/static/component-host.js" in GAME_PROMPT
    assert "Do not scan the full source tree" in GAME_PROMPT
    assert "Use at most two source inspection calls" in GAME_PROMPT
    assert "6000 characters" in GAME_PROMPT
    assert "top-level" in GAME_PROMPT and "`parameters` wrapper" in GAME_PROMPT
    assert "While a draft is open" in GAME_PROMPT
    assert "signed_error" in GAME_PROMPT and "goal_progress" in GAME_PROMPT
    assert "cycles" in GAME_PROMPT and "without an MLL call per action step" in GAME_PROMPT
    assert "physical skill" in GAME_PROMPT and "dashboards" in GAME_PROMPT
    assert "complexity_score" in GAME_PROMPT and "avatar_state" in GAME_PROMPT


class EmbodiedProvider:
    model = "main-model"

    def __init__(self, instances):
        self.requests = []
        instances.append(self)

    def stream(self, messages, tools):
        self.requests.append(deepcopy(messages))
        game_results = [m for m in messages if m.get("role") == "tool" and m.get("name", "").startswith("game_")]
        commands = [("game_inspect", {}), ("game_goal", {"x": 280}),
                    ("game_act", {"action": "right", "frames": 120}),
                    ("game_reflect", {"expected": "reach x280", "hypothesis": "motor works", "next_test": "add a block"})]
        if len(game_results) < len(commands):
            name, arguments = commands[len(game_results)]
            yield StreamEvent(kind="tool_call", tool_call={"id": f"body-call-{len(game_results)}", "name": name, "arguments": arguments})
            yield StreamEvent(kind="finish", finish_reason="tool_calls")
        else:
            yield StreamEvent(kind="text", text="Observed physical progress. This verifies the pose check only.")
            yield StreamEvent(kind="finish", finish_reason="stop")


def test_web_agent_chat_moves_its_own_body_persists_evidence_and_new_session_is_clean(tmp_path):
    instances = []
    app = WebApp(_config(tmp_path), provider_factory=lambda *_: EmbodiedProvider(instances))
    server, thread, base = _start(app)
    try:
        with pytest.raises(HTTPError) as exc:
            # Deliberately bypass the shared authenticated test helper.
            from urllib.request import urlopen
            urlopen(base + "/api/game/sessions")
        assert exc.value.code == 401
        _, _, page = _request(base + "/game/")
        assert b"game.js" in page
        _, _, script = _request(base + "/game/game.js")
        assert b"EventSource" in script
        _, _, created = _request(base + "/api/game/sessions", "POST", {"title": "physical test"})
        session = json.loads(created)["session_id"]
        _, _, created = _request(base + "/api/game/sessions", "POST", {"title": "clean"})
        clean = json.loads(created)["session_id"]
        _, _, started = _request(f"{base}/api/sessions/{session}/runs", "POST", {"message": "Reach x=280, observe and reflect"})
        run = json.loads(started)["run_id"]
        detail = _wait_for_status(base, run, "completed")
        assert len(detail["tool_calls"]) == 4
        assert all(call["status"] == "succeeded" for call in detail["tool_calls"])
        request = next(p.requests[0] for p in instances if p.requests)
        assert "You are Dagi's body" in request[0]["content"]
        _, _, payload = _request(f"{base}/api/game/sessions/{session}")
        body = json.loads(payload)
        assert body["scene"]["goal"]["passed"] is True
        assert body["scene"]["tick"] == 120
        assert body["reflections"][-1]["evidence_tick"] == 120
        assert f"stickman:{session}" == body["self"]["body_id"]
        state = StateStore(app.config.database)
        state.append_message(session, {"role": "user", "content": "authorization: Bearer dummy-export-secret"})
        state.close()
        with pytest.raises(HTTPError) as export_auth:
            from urllib.request import urlopen
            urlopen(f"{base}/api/game/sessions/{session}/export")
        assert export_auth.value.code == 401
        _, export_type, export_body = _request(f"{base}/api/game/sessions/{session}/export")
        exported = json.loads(export_body)
        assert "application/json" in export_type
        assert exported["format"] == "dagi-session-export-v1"
        assert exported["session"]["id"] == session
        assert any(m.get("role") == "assistant" and "Observed physical progress" in (m.get("content") or "") for m in exported["messages"])
        assert any((m.get("content") or "").startswith("authorization:") and "[REDACTED]" in (m.get("content") or "") for m in exported["messages"])
        assert len(exported["tool_calls"]) == 4
        assert all(call["status"] == "succeeded" for call in exported["tool_calls"])
        session_run = next(item for item in exported["runs"] if item["run_id"] == run)
        assert any(row["event"].get("kind") == "tool_call" for row in session_run["events"])
        assert session_run["provider_calls"]
        assert exported["game_world"]["tick"] == 120
        assert "provider_requests" not in exported and "private_reasoning" not in exported
        assert "dummy-export-secret" not in json.dumps(exported, ensure_ascii=False)
        _, _, payload = _request(f"{base}/api/game/sessions/{clean}")
        clean_body = json.loads(payload)
        assert clean_body["scene"]["tick"] == 0
        assert clean_body["scene"]["objects"] == []
        assert clean_body["scene"]["goal"] is None
        assert clean_body["self"]["workspace"] != body["self"]["workspace"]
        # Reopening a saved world does not replay its effects or reset its pose.
        _, _, again = _request(f"{base}/api/game/sessions/{session}")
        assert json.loads(again)["frame"] == body["frame"]
    finally:
        _stop(server, thread)
