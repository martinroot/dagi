"""Regression tests for the failures observed in session 23, not preset activities."""
from contextlib import closing
from copy import deepcopy
import json
import time

import pytest

from dagi_core.state import StateStore
from dagi_core.tools import ToolExecutionContext, ToolRegistry
from dagi_core.web import WebApp
from game.bridge import register_game, GAME_PROMPT
from game.living import advance, design, trial
from game.rigid import RigidSimulator
from game.store import GameStore, live_slot, clock_tick
from game.studio import build, configuration
from game.turns import GameContext, iterate
from game.world import fresh_world
from test_core_web import _config, _request, _start, _stop


def rigid_world():
    world=fresh_world(1)
    world["physics_engine"]="chipmunk"
    return world


def test_real_rigid_body_motor_stays_upright_and_changes_motion():
    world=rigid_world()
    idle=trial(world)
    design(world,{"operation":"policy","name":"custom","description":"test","code":"{'drive': .8}"})
    moving=trial(world)
    assert idle["upright_ratio"]>.95
    assert moving["upright_ratio"]>.9
    assert moving["dx"]>100
    assert moving["max_bone_error"]<2


def test_rectangles_rotate_and_generic_motor_joint_has_physical_effect():
    w=rigid_world()
    design(w,{"operation":"body","body":{"id":"beam","shape":"rect","x":650,"y":300,"width":90,"height":20}})
    design(w,{"operation":"joint","joint":{"id":"pivot","type":"pivot","a":"world","b":"beam","anchor":[650,300]}})
    design(w,{"operation":"joint","joint":{"id":"motor","type":"motor","a":"world","b":"beam","rate":2,"max_force":20000}})
    advance(w,120)
    obj=w["objects"][0]
    assert abs(obj["angle"])>1
    assert abs(obj["x"]-650)<2 and abs(obj["y"]-300)<2


def test_dynamic_shapes_exchange_impulses_and_do_not_fall_through_each_other():
    w=rigid_world()
    for name,y in (("bottom",500),("top",430)):
        design(w,{"operation":"body","body":{"id":name,"shape":"rect","x":650,"y":y,"width":70,"height":45,"mass":2,"restitution":.1}})
    advance(w,240)
    bottom,top=w["objects"]
    assert bottom["y"]-top["y"]>42
    assert bottom["y"]<520


def test_grip_is_a_physical_joint_and_releases_when_omitted():
    w=rigid_world()
    design(w,{"operation":"body","body":{"id":"held","shape":"circle","x":215,"y":435,"radius":8,"mass":.2}})
    simulator=RigidSimulator(w)
    simulator.step({"grip":{"object":"held","hand":"right_hand"}})
    assert w["contacts"]["grip"]=="held"
    simulator.step({})
    assert w["contacts"]["grip"] is None


def test_policy_emotion_and_parameter_channels_are_real_and_bounded():
    w=rigid_world()
    design(w,{"operation":"policy","name":"expression","description":"test","params":{"v":.5},"code":"{'emotion':{'valence':p['v'],'arousal':.8},'gaze':[350,400]}"})
    advance(w,2)
    assert w["emotion"]["valence"]==.5 and w["emotion"]["gaze"]==[350,400]
    with pytest.raises(ValueError):
        design(w,{"operation":"policy","name":"bad","description":"test","code":"{'emotion':{'valence':99}}"})


def test_historical_orphan_tool_pair_cannot_poison_a_new_game_turn(tmp_path):
    with closing(StateStore(tmp_path/"state.db")) as state:
        sid=state.create_session()
        state.append_message(sid,{"role":"user","content":"old work"})
        state.append_message(sid,{"role":"assistant","content":None,"tool_calls":[{"id":"orphan","type":"function","function":{"name":"game_observe","arguments":"{}"}}]})
        state.append_message(sid,{"role":"user","content":"new work"})
        context=GameContext(state,max_tokens=8000)
        messages=context.build(sid,"new",GAME_PROMPT,[])
        assert all(not m.get("tool_calls") for m in messages)
        assert messages[-1]["content"]=="new work"
        for _ in range(40):
            state.append_message(sid,{"role":"assistant","content":"x"*1000})
            state.append_message(sid,{"role":"user","content":"another iteration"})
        later=context.build(sid,"next",GAME_PROMPT,[])
        assert len(json.dumps(later))<12000  # History does not grow each request.


def test_game_model_surface_is_small_without_removing_registry_compatibility(tmp_path):
    with closing(StateStore(tmp_path/"state.db")) as state:
        sid=state.create_session()
        with GameStore(state.path) as store:store.create(sid)
        tools=ToolRegistry(tmp_path/"workspace",state,sid)
        register_game(tools)
        assert {t.name for t in tools.specs()}=={"game_observe","game_iteration","game_life","game_train"}
        tools.set_execution_context(ToolExecutionContext(sid,"run",0,"model"))
        assert not tools.call("game_inspect",{}).is_error


def test_fresh_canvas_frame_is_version_bound_and_optional(tmp_path):
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:None)
    server,thread,base=_start(app)
    try:
        _,_,raw=_request(base+"/api/game/sessions","POST",{"title":"vision"})
        sid=json.loads(raw)["session_id"]
        slot=live_slot(app.config.database,sid)
        slot.vision={"image":"data:image/jpeg;base64,"+"a"*15000,"version":0,"at":time.time()}
        with closing(StateStore(app.config.database)) as state:
            state.append_message(sid,{"role":"user","content":"Inspect my actual appearance"})
            context=GameContext(state,max_tokens=4000)
            messages=context.build(sid,"run","Observe truthfully.",[])
            assert messages[-1]["content"][1]["image_url"]["detail"]=="auto"
            slot.vision["version"]=99
            assert not isinstance(context.build(sid,"run","Observe truthfully.",[])[-1]["content"],list)
            slot.vision["version"]=0
            _request(f"{base}/api/game/sessions/{sid}/vision","POST",{"enabled":False})
            assert slot.vision is None
    finally:_stop(server,thread)


def test_policy_widget_replays_locally_instead_of_spending_a_model_turn(tmp_path):
    from game.studio import visual_edit
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:None)
    server,thread,base=_start(app)
    try:
        _,_,raw=_request(base+"/api/game/sessions","POST",{"title":"local control","mode":"assisted"})
        sid=json.loads(raw)["session_id"]
        with GameStore(app.config.database) as store:
            with store.mutation(sid) as world:
                design(world,{"operation":"policy","name":"saved","description":"test","code":"{'drive':.2}"})
                visual_edit(world,{"operation":"widget","widget":{"id":"replay","kind":"button","x":650,"y":70,"width":220,"height":80,"title":"Run saved code","target":{"type":"policy","name":"saved"}}})
        _,_,raw=_request(f"{base}/api/game/sessions/{sid}/interact","POST",{"widget_id":"replay","version":0})
        assert json.loads(raw)["local"]
        with closing(StateStore(app.config.database)) as state:assert not state.list_runs(sid,10)
        with GameStore(app.config.database) as store:assert store.get(sid)["life"]["running"]
    finally:_stop(server,thread)


def test_live_ticks_do_not_write_sqlite_and_continue_during_a_draft(tmp_path):
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:None)
    server,thread,base=_start(app)
    try:
        _,_,raw=_request(base+"/api/game/sessions","POST",{"title":"clock"})
        sid=json.loads(raw)["session_id"]
        app.life.ensure_clock(sid)
        with GameStore(app.config.database) as store:
            store.apply(sid,build,{"operation":"begin","objective":"offline test"})
            before=store.db.execute("SELECT world_json FROM game_worlds WHERE session_id=?",(sid,)).fetchone()[0]
            tick=store.get(sid)["tick"]
            for _ in range(15):clock_tick(app.config.database,sid)
            assert store.get(sid)["tick"]>=tick+15
            after=store.db.execute("SELECT world_json FROM game_worlds WHERE session_id=?",(sid,)).fetchone()[0]
            assert before==after
    finally:_stop(server,thread)


def test_atomic_iteration_optimizes_locally_publishes_and_starts_without_human_button(tmp_path):
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:None)
    server,thread,base=_start(app)
    try:
        _,_,raw=_request(base+"/api/game/sessions","POST",{"title":"atomic","mode":"assisted"})
        sid=json.loads(raw)["session_id"]
        result=iterate(app.config.database,sid,{"objective":"Test local parameter alternatives","changes":[
            {"operation":"policy","name":"candidate","description":"test","params":{"speed":.3},"code":"{'drive':p['speed']}"}],
            "search":{"parameter":"speed","values":[.3,.6,.8],"score":"r['dx']"}},on_publish=app.life.ensure_clock)
        assert result["published"] and len(result["search"])==3
        with GameStore(app.config.database) as store:
            w=store.get(sid)
            assert w["life"]["running"]
            assert w["policies"]["candidate"]["params"]["speed"]==.8
            tick=w["tick"]
            time.sleep(.15)
            assert store.get(sid)["tick"]>tick
        with closing(StateStore(app.config.database)) as state:assert state.list_runs(sid,10)==[]
    finally:_stop(server,thread)


def test_iteration_rejects_legacy_change_shapes_with_the_design_schema(tmp_path):
    with closing(StateStore(tmp_path/"state.db")) as state:
        sid=state.create_session()
        with GameStore(state.path) as store:store.create(sid)
        for change in ({"operation":"add","object":{"id":"ball","kind":"ball","x":250,"y":510,"radius":14}},
                       {"operation":"behavior","name":"pace","steps":[{"action":"right","frames":10}]}):
            with pytest.raises(ValueError) as exc:
                iterate(state.path,sid,{"objective":"Legacy shape","changes":[change]})
            message=str(exc.value)
            assert "game_observe view=schema" in message
            assert "policy" in message and "body" in message
            assert "id, kind, x, y, width, height, label" not in message


def test_game_iteration_description_carries_exact_change_schema():
    from game.bridge import GAME_ITERATION_DESCRIPTION
    for needle in ("policy","appearance","material","body","joint","view=schema","objective","changes"):
        assert needle in GAME_ITERATION_DESCRIPTION, needle


def _policy_change(operation_key="operation", wrapper=False, alias=False, flatten=False, as_string=False):
    inner={"name":"rhythm","description":"rhythmic dance","code":"{'drive':0.3*sin(s['t']*1.5),'intent':'dancing'}"}
    if flatten:
        change=dict(inner)
    elif wrapper:
        change={"policy":dict(inner)}
    else:
        change={operation_key:"policy",**inner}
    changes=[change]
    if as_string:
        import json as _json
        changes=_json.dumps(changes)
    return changes


@pytest.mark.parametrize("kwargs", [
    {"operation_key":"operation"},
    {"alias":True},
    {"wrapper":True},
    {"flatten":True},
    {"as_string":True},
    {"operation_key":"operation","as_string":True},
])
def test_iteration_normalizes_recognizable_change_shapes(tmp_path, kwargs):
    with closing(StateStore(tmp_path/"state.db")) as state:
        sid=state.create_session()
        with GameStore(state.path) as store:store.create(sid)
        result=iterate(state.path,sid,{"objective":"Rhythmic dance","changes":_policy_change(**kwargs),"play":False})
        assert result["published"] is True
        assert result["policy"]=="rhythm"
        with GameStore(state.path) as store:
            world=store.get(sid)
        assert "rhythm" in world["policies"] and world["active_policy"]=="rhythm"


def test_schema_view_documents_the_operation_key_on_every_change():
    from game.bridge import GAME_ITERATION_DESCRIPTION
    assert '{\"operation\":\"policy\"' in GAME_ITERATION_DESCRIPTION or '"operation"' in GAME_ITERATION_DESCRIPTION


def test_game_turn_cap_grants_discovery_headroom():
    from game.turns import game_call_cap, GAME_TURN_CALL_CAP
    assert GAME_TURN_CALL_CAP == 16
    assert game_call_cap(25) == 16
    assert game_call_cap(6) == 6
    assert game_call_cap(100) == 16


def test_failed_atomic_change_does_not_publish_or_replace_working_world(tmp_path):
    with closing(StateStore(tmp_path/"state.db")) as state:
        sid=state.create_session()
        with GameStore(state.path) as store:store.create(sid)
        result=iterate(state.path,sid,{"objective":"Test delayed failure","changes":[{"operation":"policy","name":"bad","description":"test","code":"{'drive':0 if s['t']<.5 else 1/0}"}]})
        assert not result["published"]
        with GameStore(state.path) as store:
            w=store.get(sid)
        assert w["version"]==0 and w["draft"] is None and not w["policies"]


def test_late_controller_fault_disables_only_the_policy_and_keeps_physics_running(tmp_path):
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:None)
    server,thread,base=_start(app)
    try:
        _,_,raw=_request(base+"/api/game/sessions","POST",{"title":"late fault"})
        sid=json.loads(raw)["session_id"]
        with GameStore(app.config.database) as store:
            with store.mutation(sid) as w:
                design(w,{"operation":"policy","name":"fault","description":"fails on later input","code":"{'drive':0 if s['t']<.05 else 1/0}"})
                w["life"]["running"]=True
        for _ in range(20):clock_tick(app.config.database,sid)
        with GameStore(app.config.database) as store:
            w=store.get(sid)
            assert w["tick"]>=18
            assert w["active_policy"] is None and w["failed_policy"]=="fault"
            assert w["policy_error"] and w["life"]["running"]
            assert "fault" in w["policies"]  # Failed source remains available for diagnosis.
    finally:_stop(server,thread)
