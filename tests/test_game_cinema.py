"""Authored-film channels, real rigid-body rotation, and honest assistance."""
from copy import deepcopy
import math
import pytest
from game.cinema import validate_look
from game.workshop import initialize_physical

def presentation_world(w):
    initialize_physical(w)
    return w

from game.director import command,define
from game.living import advance,validate_control
from game.world import fresh_world
from game.rigid import RigidSimulator
from game.learning import supports
from game.character import physical_shape,bone_lengths




def test_look_and_speech_are_bounded_presentation_and_reset_when_omitted():
    w=presentation_world(fresh_world(1));before=deepcopy(w['character']);shape=physical_shape(before)
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
    with pytest.raises(ValueError):validate_look(presentation_world(fresh_world(1)),look)




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
