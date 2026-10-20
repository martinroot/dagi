"""Agent skill integration without paid provider calls or browser-reported scores."""
from contextlib import closing
from copy import deepcopy
import json
import time
from urllib.error import HTTPError

import pytest
from dagi_core.provider import StreamEvent
from dagi_core.state import StateStore
from dagi_core.web import WebApp
from game import agent_runtime as runtime
from game.store import GameStore
from game.world import fresh_world
from test_core_web import _config, _request, _start, _stop, _wait_for_status


def body():
    w=fresh_world(1);runtime.initialize(w);return w


@pytest.mark.parametrize('skill',runtime.CATALOG)
def test_all_included_skills_pass_shared_server_motion_checks(skill):
    result=runtime.evaluate(skill)
    assert result['passed']
    assert result['samples']>500
    assert all(check['passed'] for check in result['checks'])
    assert not runtime.CATALOG[skill]['learned']


def test_decomposition_runs_in_order_and_saves_evidence_without_changing_criteria():
    w=body();steps=list(runtime.CATALOG)
    ids=runtime.command(w,{'steps':steps,'goal':'Six skills'},now=100)['execution_ids']
    runtime.advance(w,now=145)
    state=runtime.observe(w,now=145)
    assert not state['active'] and not state['queue']
    assert [h['execution_id'] for h in state['history']]==ids
    assert all(h['status']=='passed' for h in state['history'])
    assert state['history'][1]['started_at']==106.2
    assert not w['life']['running']


def test_failed_check_blocks_dependent_steps_and_cannot_be_overridden(monkeypatch):
    w=body();runtime.command(w,{'steps':['somersault','ladder']},now=100)
    monkeypatch.setattr(runtime,'evaluate',lambda skill:{'passed':False,'checks':[{'name':'broken','passed':False}]})
    runtime.advance(w,now=110)
    state=w['agent_runtime']
    assert [h['status'] for h in state['history']]==['failed','blocked']
    assert not state['active'] and not state['queue']
    with pytest.raises(ValueError):runtime.command(w,{'skill':'somersault','score':100},now=111)


def test_stop_cancels_queue_and_freezes_partial_pose():
    w=body();runtime.command(w,{'steps':['somersault','ladder']},now=100)
    runtime.command(w,{'action':'stop'},now=102)
    assert not w['agent_runtime']['active']
    assert [h['status'] for h in w['agent_runtime']['history']]==['cancelled','cancelled']
    assert w['agent_runtime']['last_pose']=={'index':0,'time':2}
    runtime.advance(w,now=1000)
    assert len(w['agent_runtime']['history'])==2


def test_practice_is_opt_in_and_selects_least_repeated_skill():
    w=body();runtime.advance(w,now=time.time()+100)
    assert w['agent_runtime']['active'] is None
    runtime.command(w,{'action':'practice','enabled':True},now=100)
    runtime.advance(w,now=103)
    assert w['agent_runtime']['active']['id']=='somersault'
    runtime.advance(w,now=113)
    assert w['agent_runtime']['active']['id']=='wall_flip'


def test_compositions_notes_validation_and_session_isolation():
    w=body();other=body()
    runtime.command(w,{'action':'save','name':'warmup','steps':['vault','ladder']},now=100)
    runtime.command(w,{'skill':'warmup'},now=101)
    runtime.advance(w,now=120)
    receipt=w['agent_runtime']['history'][0]['execution_id']
    runtime.command(w,{'action':'note','receipt':receipt,'note':'Checked geometry'},now=121)
    assert not other['agent_runtime']['plans'] and not other['agent_runtime']['history']
    assert len(w['agent_runtime']['notes'])==1
    for args in ({'steps':[{}]}, {'skill':[]}, {'skill':'missing'}, {'steps':['vault']*7}, {'action':'practice','enabled':'yes'}, {'skill':'vault','wait':'yes'}, {'action':'note','receipt':'fake','note':'invented'}):
        with pytest.raises(ValueError):runtime.command(w,args,now=122)


def test_wait_cancellation_is_durable(tmp_path):
    db=tmp_path/'state.db'
    with closing(StateStore(db)) as state:sid=state.create_session()
    with GameStore(db) as store:
        store.create(sid)
        with store.mutation(sid) as world:runtime.initialize(world)
    result=runtime.execute(db,sid,{'skill':'ladder','wait':True},cancelled=lambda:True)
    assert result['cancelled']
    with GameStore(db) as store:assert store.get(sid)['agent_runtime']['history'][0]['status']=='cancelled'


class SkillProvider:
    model='test-model'
    def __init__(self,requests):self.calls=0;self.requests=requests
    def stream(self,messages,tools):
        self.calls+=1;self.requests.append((deepcopy(messages),deepcopy(tools)))
        if self.calls==1:
            return iter([StreamEvent(kind='tool_call',tool_call={'id':'skill-1','name':'game_skill','arguments':{'action':'run','skill':'somersault','goal':'A checked flip','wait':True}}),StreamEvent(kind='finish',finish_reason='tool_calls')])
        return iter([StreamEvent(kind='text',text='Сальто завершено. Серверные проверки пройдены.'),StreamEvent(kind='finish',finish_reason='stop')])


def test_chat_uses_new_tool_and_receives_completed_server_evidence(tmp_path):
    requests=[];app=WebApp(_config(tmp_path),provider_factory=lambda *_:SkillProvider(requests))
    server,thread,base=_start(app)
    try:
        _,_,raw=_request(base+'/api/game/sessions','POST',{'title':'Agent','agent':True})
        sid=json.loads(raw)['session_id']
        _,_,raw=_request(base+f'/api/sessions/{sid}/runs','POST',{'message':'Сделай сальто и дождись результата'})
        run=json.loads(raw)['run_id'];_wait_for_status(base,run,'completed',timeout=15)
        _,_,raw=_request(base+f'/api/game/sessions/{sid}/agent');snapshot=json.loads(raw)
        assert snapshot['history'][0]['status']=='passed'
        assert len(requests)==2
        prompt=requests[0][0][0]['content']
        assert 'DAGI_AGENT_PASSPORT_DATA' in prompt and 'game/static/motion.js' in prompt
        names={t['function']['name'] for t in requests[0][1]}
        assert names=={'game_observe','game_skill'}
        assert any(m['role']=='tool' and 'passed' in m['content'] for m in requests[1][0])
        with pytest.raises(HTTPError) as exc:_request(base+'/api/game/sessions','POST',{'film':True})
        assert exc.value.code==400
    finally:_stop(server,thread)


def test_agent_state_api_requires_authentication_and_persists_across_reopen(tmp_path):
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:pytest.fail('Local controls must not call a provider'))
    server,thread,base=_start(app)
    try:
        _,_,raw=_request(base+'/api/game/sessions','POST',{'agent':True});sid=json.loads(raw)['session_id']
        _request(base+f'/api/game/sessions/{sid}/agent','POST',{'action':'run','skill':'ladder'})
        with GameStore(app.config.database) as store:
            with store.mutation(sid) as world:world['agent_runtime']['active']['started_at']-=11
        _,_,raw=_request(base+f'/api/game/sessions/{sid}/agent');data=json.loads(raw)
        assert data['history'][0]['status']=='passed'
        with closing(StateStore(app.config.database)) as state:assert not state.list_runs(sid)
        from urllib.request import urlopen
        with pytest.raises(HTTPError) as exc:urlopen(base+f'/api/game/sessions/{sid}/agent')
        assert exc.value.code==401
    finally:_stop(server,thread)
