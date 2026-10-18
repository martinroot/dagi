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
from game.bridge import register_game
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
        assert "Your stickman IS your body" in request[0]["content"]
        _, _, payload = _request(f"{base}/api/game/sessions/{session}")
        body = json.loads(payload)
        assert body["scene"]["goal"]["passed"] is True
        assert body["scene"]["tick"] == 120
        assert body["reflections"][-1]["evidence_tick"] == 120
        assert f"stickman:{session}" == body["self"]["body_id"]
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
