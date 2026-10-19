"""Authored-film channels, real rigid-body rotation, and honest assistance."""
from copy import deepcopy
import math
import pytest
from game.cinema import premiere,validate_look
from game.director import command,define
from game.living import advance,validate_control
from game.world import fresh_world
from game.rigid import RigidSimulator
from game.learning import supports
from game.character import physical_shape,bone_lengths


def test_premiere_is_optional_and_rig_cannot_bypass_unassisted_guards():
    w=fresh_world(1)
    assert not w['body_control'].get('stage_rig') and not w['projects']
    with pytest.raises(ValueError,match='explicit'):validate_control(w,{'rig':{'position':[500,440],'angle':1.57}})
    premiere(w)
    assert supports(w)==1 and w['body_control']['mode']=='physical'
    assert w['learning']['skills']=={} and not w['life']['running']


def test_look_and_speech_are_bounded_presentation_and_reset_when_omitted():
    w=premiere(fresh_world(1));before=deepcopy(w['character']);shape=physical_shape(before)
    define(w,{'name':'channels','description':'channels','files':{'main.js':"module.exports=()=>({look:{character:{features:{hair:'bob',detail:1}},reveal:{progress:.5}},speech:{text:'Hello 👋',progress:.6},camera:{zoom:9,cut:true},expression:{blink_left:1,smile:.8}})"}})
    result=command(w)
    assert w['character']==before and physical_shape(w['character'])==shape
    assert w['direction']['speech']['text']=='Hello 👋'
    assert result['emotion']['blink_left']==1
    define(w,{'name':'channels','description':'reset','files':{'main.js':'module.exports=()=>({})'}})
    result=command(w)
    assert w['direction']['look']=={} and w['direction']['speech'] is None
    assert result['emotion']['blink_left']==0 and result['emotion']['smile']==0


@pytest.mark.parametrize('look',[
    {'character':{'head_radius':50}}, {'character':{'features':{'hair':'remote.png'}}},
    {'character':{'features':{'detail':float('nan')}}}, {'environment':{'sky_top':'javascript:evil'}},
    {'art':{'layers':[{}]}}, {'reveal':{'progress':2}},
])
def test_presentation_rejects_physics_mutations_and_invalid_payloads(look):
    with pytest.raises(ValueError):validate_look(premiere(fresh_world(1)),look)


def test_complete_film_really_rotates_dynamic_body_and_lands_then_survives_rebuild():
    w=premiere(fresh_world(1));sim=RigidSimulator(w);angles=[];air=[];errors=[];shots=[]
    for i in range(38*60):
        advance(w,1,simulator=sim,diagnostics=False)
        assert not w['project_error']
        if i%30==0:
            angles.append(sim.segments['hip'][0].angle)
            air.append(w['nodes']['hip']['y'])
            errors.append(max(abs(math.dist((w['nodes'][a]['x'],w['nodes'][a]['y']),(w['nodes'][b]['x'],w['nodes'][b]['y']))-l) for a,b,l in bone_lengths(w)))
            shots.append(w['direction']['camera']['zoom'])
        # Save/reload/viewer reconnect must not discard completed angular turns.
        if i==30*60:sim=RigidSimulator(w)
    assert max(angles)-min(angles)>6.1 and min(air)<315
    assert abs(sim.segments['hip'][0].angle-(math.pi/2+2*math.pi-.08))<.2
    assert w['nodes']['head']['y']<w['nodes']['hip']['y']-60
    assert len(w['contacts']['support'])>=2 and max(errors)<1.5
    assert w['energy']['stage_work']>0 and supports(w)==1
    assert max(shots)>=8 and min(shots)<=1.1


def test_time_limit_retries_one_heavy_frame_and_still_kills_runaway_code():
    import quickjs
    import game.director as D
    from game.director import command
    w=fresh_world(1)
    define(w,{'name':'slow','description':'slow','files':{'main.js':"module.exports=()=>({control:{}})"},'entry':'main.js','activate':True})
    calls={'n':0}
    real=D._compiled
    def once_interrupted(project,scope,budget=D.JS_TIME_BUDGET):
        ctx,main=real(project,scope,budget)
        def wrapper(data):
            calls['n']+=1
            if calls['n']==1:raise quickjs.JSException('InternalError: interrupted')
            return main(data)
        return ctx,wrapper
    D._compiled=once_interrupted
    try:
        command(w)
        assert calls['n']==2 and 'js_budget' not in w
    finally:
        D._compiled=real
    # runaway code still fails loudly (the watchdog is not disabled by escalation)
    define(w,{'name':'runaway','description':'runaway','files':{'main.js':"module.exports=()=>{while(true){}}"},'entry':'main.js','activate':True,'replace':True})
    w['active_project']='runaway'
    with pytest.raises(ValueError,match='project runtime'):
        for _ in range(4):command(w)


def test_rig_release_does_not_freeze_or_reposition_body():
    w=premiere(fresh_world(1));sim=RigidSimulator(w)
    advance(w,120,simulator=sim,diagnostics=False)
    y=w['nodes']['hip']['y'];w['active_project']=None
    advance(w,90,simulator=sim,diagnostics=False)
    assert w['nodes']['hip']['y']>y+15


def test_film_api_creates_separate_session_and_playback_does_not_initialize_provider(tmp_path):
    from test_core_web import _config,_request,_start,_stop
    from dagi_core.web import WebApp
    from game.store import GameStore
    import json
    def forbidden(*a):raise AssertionError('No provider for local film playback')
    config=_config(tmp_path);app=WebApp(config,provider_factory=forbidden)
    server,thread,base=_start(app)
    try:
        status,_,raw=_request(base+'/api/game/sessions','POST',{'title':'Film','film':True})
        assert status==201;id=json.loads(raw)['session_id']
        with GameStore(config.database) as store:
            w=store.get(id);assert w['active_project']=='Hello Dagi' and w['body_control']['stage_rig']
        status,_,raw=_request(base+f'/api/game/sessions/{id}/life','POST',{'action':'play'})
        assert status==200
        _request(base+f'/api/game/sessions/{id}/life','POST',{'action':'pause'})
        with GameStore(config.database) as store:
            assert not store.get(id)['life']['running']
    finally:_stop(server,thread)
