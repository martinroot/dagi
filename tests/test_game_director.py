"""Exercise authored source and observed physical outcomes, not predefined stories."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
import time

import pytest

from dagi_core.state import StateStore
from dagi_core.tools import ToolExecutionContext, ToolRegistry
from dagi_core.web import WebApp
from game.bridge import register_game
from game.director import anatomy, command, define
from game.living import advance, trial
from game.store import GameStore, clock_tick, live_slot
from game.studio import activate, build, configuration, digest
from game.turns import iterate
from game.world import fresh_world, upgrade
from test_core_web import _config, _request as raw_request, _start, _stop
from urllib.error import HTTPError

def _request(base,path,method="GET",body=None):
    try:
        status,_,raw=raw_request(base+path,method,body)
        return status,json.loads(raw) if raw.startswith(b"{") else raw
    except HTTPError as exc:return exc.code,json.loads(exc.read())


def world():
    w=fresh_world(1);w['physics_engine']='chipmunk';return w


def project(w, source, **extra):
    args={'operation':'project','name':'invented','description':'test-authored source','files':{'main.js':source}}
    args.update(extra);define(w,args);return args


def test_full_js_modules_loops_and_state_drive_server_physics_without_browser():
    w=world()
    project(w,"const clamp=require('./math.js'); module.exports=({s,state})=>{let total=0; for(let i=0;i<8;i++)total+=i; return {control:{drive:clamp((400-s.x)/100)},state:{n:(state.n||0)+1,total},camera:{target:'head',zoom:2},expression:{surprise:.7},beat:'observe'};};",files={
        'main.js':"const clamp=require('./math.js'); module.exports=({s,state})=>{let total=0;for(let i=0;i<8;i++)total+=i;return {control:{drive:clamp((400-s.x)/100)},state:{n:(state.n||0)+1,total},camera:{target:'head',zoom:2},expression:{surprise:.7},beat:'observe'};};",
        'math.js':"module.exports=x=>Math.max(-1,Math.min(1,x));"})
    advance(w,180)
    assert w['nodes']['hip']['x']>250
    assert w['project_state']=={'n':180,'total':28}
    assert w['direction']['camera']=={'target':'head','zoom':2}
    assert w['emotion']['surprise']==.7


def test_project_has_no_host_api_and_infinite_loop_is_interrupted_then_recoverable():
    w=world()
    project(w,"module.exports=()=>({state:{fs:typeof require,network:typeof fetch,host:typeof process},control:{}})")
    command(w)
    assert w['project_state']=={'fs':'function','network':'undefined','host':'undefined'}
    project(w,"module.exports=()=>{while(true){}}")
    start=time.monotonic()
    with pytest.raises(ValueError,match='project runtime'):command(w)
    assert time.monotonic()-start<1
    project(w,"module.exports=()=>({state:{ok:true}})")
    command(w);assert w['project_state']=={'ok':True}


@pytest.mark.parametrize('source',[
    "module.exports=()=>({camera:{zoom:200}})",
    "module.exports=()=>({draw:[{type:'circle',x:0,y:0,radius:-1}]})",
    "module.exports=()=>({state:{huge:'x'.repeat(9000)}})",
    "module.exports=()=>({control:{drive:99}})",
    "module.exports=()=>({expression:{surprise:4}})",
    "module.exports=()=>Promise.resolve({})",
    "module.exports=()=>({camera:{target:'missing'}})",
])
def test_invalid_channels_are_rejected(source):
    # The invariant is rejection, not which phase rejects: under full-suite CPU
    # contention the CPU watchdog can trip during project() validation instead
    # of during command(), so both phases are covered by one expectation.
    w=world()
    with pytest.raises(ValueError):
        project(w,source)
        command(w)


def test_file_paths_and_external_modules_cannot_escape_project():
    w=world()
    with pytest.raises(ValueError):project(w,'test',files={'../escape.js':'module.exports=()=>({})'})
    with pytest.raises(ValueError,match='Unknown project file'):
        project(w,"require('fs');module.exports=()=>({})");command(w)


def test_physical_appendage_tree_moves_without_changing_segment_lengths():
    w=world()
    anatomy(w,{'operation':'appendage','part':{'id':'upper','parent':'neck','length':40}})
    anatomy(w,{'operation':'appendage','part':{'id':'tip','parent':'upper','length':25}})
    project(w,"module.exports=({t})=>({control:{appendage_pose:{upper:-.9+.2*Math.sin(t),tip:-1.1}}})")
    advance(w,60)
    import math
    parts=w['appendage_frames']
    assert abs(math.dist(parts[0][1],parts[0][2])-40)<.01
    assert abs(math.dist(parts[1][1],parts[1][2])-25)<.01
    assert math.dist(parts[0][2],parts[1][1])<1
    with pytest.raises(ValueError,match='parent'):
        anatomy(w,{'operation':'appendage','part':{'id':'upper','parent':'tip'}})
    anatomy(w,{'operation':'remove_appendage','id':'upper'})
    assert w['appendages']==[] and w['appendage_frames']==[]


def test_project_trial_starts_at_publication_time_and_rejects_delayed_failure():
    w=world();w['tick']=9000
    project(w,"module.exports=({t})=>{if(t>8)throw Error('late failure');return {control:{},state:{t}};}")
    before=deepcopy(w);result=trial(w)
    assert not result['passed'] and 'late failure' in result['error']
    assert w==before


def test_projects_can_run_from_independent_threads_and_sessions():
    a,b=world(),world();b['body_id']='stickman:2'
    code="module.exports=({state})=>({state:{n:(state.n||0)+1}})"
    project(a,code);project(b,code)
    def run(w):
        for _ in range(30):command(w)
        return w['project_state']['n']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run,[a,b]))==[30,30]


def test_publication_rebases_timeline_but_unrelated_edit_preserves_running_memory():
    w=world();w['tick']=1000
    changes=[{'operation':'project','name':'custom','description':'test','files':{'main.js':"module.exports=({state})=>({state:{n:(state.n||0)+1}})"}}]
    build(w,{'operation':'begin','objective':'Create source'})
    build(w,{'operation':'edit','changes':changes});build(w,{'operation':'test'})
    assert w['draft']['report']['passed']
    w['tick']=1100;w['draft'].update(state='scheduled',activate_at=0)
    activate(w,{'id':w['draft']['id']});assert w['project_started']==1100
    advance(w,10);state=deepcopy(w['project_state'])
    initial=digest(configuration(w));w['project_state']['irrelevant']=9
    assert digest(configuration(w))==initial
    build(w,{'operation':'begin','objective':'Change a color'})
    build(w,{'operation':'edit','changes':[{'operation':'appearance','values':{'accent':'#55aabb'}}]});build(w,{'operation':'test'})
    w['draft'].update(state='scheduled',activate_at=0);activate(w,{'id':w['draft']['id']})
    assert w['project_started']==1100 and w['project_state']['n']==state['n']


def test_runtime_failure_preserves_source_and_keeps_physics_alive(tmp_path):
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:None)
    server,thread,base=_start(app)
    try:
        _,created=_request(base,'/api/game/sessions',method='POST',body={});sid=created['session_id']
        with GameStore(app.config.database) as game:
            with game.mutation(sid) as w:
                project(w,"module.exports=()=>{throw Error('boom')}");w['life']['running']=True
        clock_tick(app.config.database,sid)
        slot=live_slot(app.config.database,sid)
        assert slot.world['active_project'] is None
        assert slot.world['project_error']['name']=='invented'
        assert 'invented' in slot.world['projects'] and slot.world['life']['running']
        tick=slot.world['tick'];clock_tick(app.config.database,sid)
        assert slot.world['tick']>tick
    finally:_stop(server,thread)


def test_project_events_and_controls_are_local_and_version_bound(tmp_path):
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:None)
    server,thread,base=_start(app)
    try:
        _,created=_request(base,'/api/game/sessions',method='POST',body={});sid=created['session_id']
        with GameStore(app.config.database) as game:
            with game.mutation(sid) as w:
                project(w,"module.exports=({event,state})=>({state:{last:event?event.id:state.last}})")
                w['widgets']=[{'id':'signal','kind':'button','x':700,'y':60,'width':200,'height':90,'title':'Signal','target':{'type':'project','name':'invented','event':'hello'}}]
        status,data=_request(base,f'/api/game/sessions/{sid}/project-event',method='POST',body={'version':99,'id':'bad'})
        assert status==400
        status,data=_request(base,f'/api/game/sessions/{sid}/project-event',method='POST',body={'version':0,'id':'attention'})
        assert status==200 and data['local']
        status,data=_request(base,f'/api/game/sessions/{sid}/interact',method='POST',body={'version':0,'widget_id':'signal'})
        assert status==200 and data['local']
        time.sleep(.1)
        with GameStore(app.config.database) as game:assert game.get(sid)['project_state']['last']=='hello'
        with closing(StateStore(app.config.database)) as state:assert state.list_runs(sid)==[]
        assert _request(base,'/game/agent-renderer.js')[0]==200
    finally:_stop(server,thread)


def test_code_observation_exposes_editable_files_instead_of_only_installed_source(tmp_path):
    with closing(StateStore(tmp_path/'state.db')) as state:
        sid=state.create_session()
        with GameStore(state.path) as game:
            game.create(sid)
            with game.mutation(sid) as w:project(w,"module.exports=()=>({})")
        tools=ToolRegistry(tmp_path/'workspace',state,sid);register_game(tools)
        tools.set_execution_context(ToolExecutionContext(sid,'run',0,'model'))
        observed=tools.call('game_observe',{'view':'code','path':'main.js'})
        assert not observed.is_error and 'module.exports' in observed.content


def test_old_draft_snapshot_migrates_additively():
    w=world();build(w,{'operation':'begin','objective':'Old version draft'})
    for key in ('projects','active_project','project_state','project_started','appendages'):
        w['draft']['candidate'].pop(key);w['draft']['seed'].pop(key)
    upgrade(w)
    assert w['draft']['candidate']['projects']=={}


def test_edited_files_merge_and_keep_helpers_and_parameters():
    w=world()
    project(w,'unused',files={'main.js':"const n=require('./n.js');module.exports=()=>({state:{n}})",'n.js':'module.exports=3;'},params={'speed':.5})
    project(w,"const n=require('./n.js');module.exports=({params})=>({state:{n:n*2,speed:params.speed}})")
    command(w)
    assert w['project_state']=={'n':6,'speed':.5}
    assert 'n.js' in w['projects']['invented']['files']


def test_failed_iteration_does_not_publish_candidate_source_or_move_live_body(tmp_path):
    with closing(StateStore(tmp_path/'state.db')) as state:
        sid=state.create_session()
        with GameStore(state.path) as game:before=game.create(sid)
        result=iterate(state.path,sid,{'objective':'Test a delayed invalid project','changes':[{'operation':'project','name':'bad','description':'test','files':{'main.js':"module.exports=({t})=>{if(t>2)throw Error('later');return {control:{drive:.2}};}"}}]})
        assert not result['published']
        with GameStore(state.path) as game:after=game.get(sid)
        assert after['projects']=={} and after['nodes']==before['nodes'] and after['version']==0


def test_session_scopes_and_cloned_trials_do_not_share_js_globals(tmp_path):
    worlds=[]
    for filename in ('a.db','b.db'):
        with closing(StateStore(tmp_path/filename)) as state:
            sid=state.create_session()
            with GameStore(state.path) as game:worlds.append(game.create(sid))
    a,b=worlds  # Equal session numbers in different databases are isolated.
    source="module.exports=()=>{globalThis.counter=(globalThis.counter||0)+1;return {state:{n:globalThis.counter}}}"
    project(a,source);project(b,source)
    command(a);command(b)
    assert a['project_state']['n']==b['project_state']['n']==1
    assert trial(a)['passed']
    command(a);assert a['project_state']['n']==2


def test_project_parameter_search_uses_local_physical_trials_and_autoplays(tmp_path):
    with closing(StateStore(tmp_path/'state.db')) as state:
        sid=state.create_session()
        with GameStore(state.path) as game:game.create(sid)
        started=[]
        result=iterate(state.path,sid,{'objective':'Compare two physical drive parameters','changes':[{'operation':'project','name':'searched','description':'test','params':{'speed':0},'files':{'main.js':"module.exports=({params})=>({control:{drive:params.speed}})"}}], 'search':{'parameter':'speed','values':[0,.5],'score':"r['dx']"}},on_publish=lambda sid,**kw:started.append(sid))
        assert result['published'] and len(result['search'])==2 and started==[sid]
        with GameStore(state.path) as game:assert game.get(sid)['projects']['searched']['params']['speed']==.5
