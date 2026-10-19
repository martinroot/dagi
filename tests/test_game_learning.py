"""Measured skill progression, source-bound evidence and honest failure memory."""
from copy import deepcopy
from contextlib import closing
import json
import pytest
from dagi_core.state import StateStore
from game.world import fresh_world
from game.workshop import initialize_physical,joint
from game.director import define
from game.learning import plan,assess,record,summary,Metrics,binding,handle
from game.store import GameStore
from game.turns import iterate

CODE="module.exports=({params})=>({control:{muscles:{right_hand:params.effort}}});"


def world():
 w=fresh_world(1);initialize_physical(w);w['physics_engine']='chipmunk';w['gravity']=0
 define(w,{'operation':'project','name':'arm','description':'Test muscular action','params':{'effort':0},'files':{'main.js':CODE}})
 return w


def skill(id='arm',depends=None,minimum=.01):
 return {'id':id,'title':id,'depends':depends or [],'program':'arm','metrics':[{'name':'work','expression':"s['energy']['muscle_work']",'reduce':'last','target':{'min':minimum}}],
         'score':"r['metrics']['work']",'success':"r['metrics']['work']>=0.01",'guards':["r['mode']=='physical' and r['external_supports']==0 and r['powered_motors']==0"],
         'cases':[{'id':'train','frames':30,'start':'neutral','split':'train'},{'id':'validation','frames':30,'start':'neutral','split':'validation','velocity':[3,0]}]}


def setplan(w,skills=None,target='arm'):
 return plan(w,{'action':'plan','goal':'Measured muscle action','target':target,'reason':'Separate ability and composition','skills':skills or [skill()]})


def program(effort):return {'operation':'project','name':'arm','description':'Test muscular action','params':{'effort':effort},'files':{'main.js':CODE}}


def test_dense_metrics_duration_longest_transitions_and_numeric_integral():
 c={'metrics':[{'name':name,'expression':"s['ok']" if reducer in ('duration','longest','transitions') else "s['value']",'reduce':reducer} for name,reducer in [('duration','duration'),('longest','longest'),('transitions','transitions'),('area','integral'),('mean','mean')]]}
 meter=Metrics(c,{'ok':False,'value':0})
 for ok in [False,True,True,False,True,True,True]:meter.sample({'ok':ok,'value':2})
 values=meter.values();assert values['duration']==pytest.approx(5/60) and values['longest']==pytest.approx(3/60)
 assert values['transitions']==2 and values['area']==pytest.approx(14/60) and values['mean']==2


def test_boolean_score_or_mis_typed_metric_never_certifies_success():
 w=world();c=skill();c['score']='True';setplan(w,[c]);r=assess(w,'arm');assert not r['passed'] and r['score'] is None
 c=skill();c['metrics'][0]['expression']='True';setplan(w,[c]);r=assess(w,'arm');assert not r['passed'] and 'numeric' in r['cases'][0]['error']


def test_noop_program_executes_but_does_not_master_skill_and_dense_sampling_runs_each_tick():
 w=world();setplan(w);r=assess(w,'arm')
 assert not r['passed'] and r['score']==0 and r['guards_pass']
 record(w,'arm',r,applied=True)
 assert summary(w)['status']=='training' and summary(w)['skills'][0]['status']=='ready'


def test_nonzero_internal_muscle_work_is_measured_and_dependent_skill_stays_unverified():
 w=world();define(w,program(.25));setplan(w,[skill(),skill('composed',['arm'])],target='composed')
 r=assess(w,'arm');assert r['passed'] and r['score']>0
 record(w,'arm',r,applied=True)
 s=summary(w);assert s['status']=='training' and s['focus']=='composed'
 assert s['skills'][1]['status']=='ready'
 record(w,'composed',assess(w,'composed'),applied=True)
 assert summary(w)['status']=='mastered'


@pytest.mark.parametrize('mutation',['source','physics','criteria'])
def test_mastery_expires_when_bound_source_physics_or_contract_changes(mutation):
 w=world();define(w,program(.25));setplan(w);record(w,'arm',assess(w,'arm'),applied=True);assert summary(w)['status']=='mastered'
 if mutation=='source':define(w,program(0))
 elif mutation=='physics':w['gravity']=981
 else:setplan(w,[skill(minimum=100)])
 assert summary(w)['status']=='training'


def test_unapplied_experiment_cannot_grant_mastery_even_if_its_tests_passed():
 w=world();define(w,program(.25));setplan(w);record(w,'arm',assess(w,'arm'),applied=False)
 assert summary(w)['status']=='training'


def test_external_world_support_is_detected_through_an_indirect_constraint_chain():
 from game.workshop import body
 w=world();define(w,program(.25));setplan(w)
 body(w,{'operation':'body','body':{'id':'beam','shape':'rect','x':180,'y':440,'width':8,'height':20,'mass':1}})
 for j in [{'id':'a','type':'weld','a':'world','b':'beam','anchor_a':[180,440]},{'id':'b','type':'weld','a':'beam','b':'self:hip'}]:joint(w,{'operation':'joint','joint':j})
 r=assess(w,'arm');assert not r['passed'] and not r['guards_pass']
 assert r['cases'][0]['report']['external_supports']==1


def test_cycle_unknown_prerequisite_and_missing_validation_rejected_atomically():
 w=world();before=deepcopy(w['learning'])
 for skills in ([skill('a',['b']),skill('b',['a'])],[skill('a',['missing'])]):
  with pytest.raises(ValueError):setplan(w,skills,target='a')
  assert w['learning']==before
 c=skill();c['cases']=c['cases'][:1]
 with pytest.raises(ValueError,match='validation'):setplan(w,[c])


def test_plateau_blocks_further_paid_practice_and_same_plan_does_not_reset_budget():
 w=world();c=skill();c['plateau_limit']=2;setplan(w,[c]);r=assess(w,'arm')
 for _ in range(2):record(w,'arm',r,applied=False)
 assert summary(w)['status']=='blocked'
 setplan(w,[c]);assert summary(w)['status']=='blocked' and summary(w)['skills'][0]['attempts']==2


def test_plan_survives_sqlite_restart_and_hypotheses_must_cite_receipt(tmp_path):
 path=tmp_path/'state.db'
 with closing(StateStore(path)) as state:sid=state.create_session()
 with GameStore(path) as game:game.create(sid)
 args={'action':'plan','goal':'test','target':'arm','reason':'first criteria','skills':[skill()]};handle(path,sid,args)
 with pytest.raises(ValueError,match='cite'):handle(path,sid,{'action':'note','skill':'arm','attempt':'fake','hypothesis':'x','next_change':'y'})
 with GameStore(path) as game:assert game.get(sid)['learning']['goal']=='test'


def setup_store(tmp_path,minimum=.01):
 path=tmp_path/'state.db'
 with closing(StateStore(path)) as state:sid=state.create_session()
 with GameStore(path) as game:
  game.create(sid)
  with game.mutation(sid) as w:
   w.update(world());w['session_id']=sid;setplan(w,[skill(minimum=minimum)])
 return path,sid


def test_iteration_rejects_fitness_plateau_and_saves_failed_candidate_source(tmp_path):
 path,sid=setup_store(tmp_path)
 r=iterate(path,sid,{'objective':'No improvement','skill':'arm','changes':[program(0)],'play':False})
 assert not r['published'] and r['fitness']['score']==0
 with GameStore(path) as game:
  w=game.get(sid);assert w['version']==0 and w['learning']['skills']['arm']['working']['files']['main.js']==CODE


def test_improvement_can_publish_without_false_mastery_then_regression_is_blocked(tmp_path):
 path,sid=setup_store(tmp_path,minimum=100)
 r=iterate(path,sid,{'objective':'Better muscle action','skill':'arm','changes':[program(.15)],'play':False})
 assert r['published'] and not r['fitness']['passed'] and r['learning']['status']=='training'
 r=iterate(path,sid,{'objective':'Regression','skill':'arm','changes':[program(0)],'play':False})
 assert not r['published']
 with GameStore(path) as game:assert game.get(sid)['projects']['arm']['params']['effort']==.15


def test_skill_success_and_recovery_cases_are_real_checks_not_tool_status(tmp_path):
 path,sid=setup_store(tmp_path)
 r=iterate(path,sid,{'objective':'Use muscle','skill':'arm','changes':[program(.25)],'play':False})
 assert r['published'] and r['fitness']['passed'] and r['learning']['status']=='mastered'
 handle(path,sid,{'action':'evaluate','skill':'arm'})
 with GameStore(path) as game:assert summary(game.get(sid))['status']=='mastered'


def test_cancellation_does_not_store_a_partial_evaluation(tmp_path):
 path,sid=setup_store(tmp_path)
 with pytest.raises(ValueError,match='cancelled'):handle(path,sid,{'action':'evaluate','skill':'arm'},lambda:True)
 with GameStore(path) as game:assert not game.get(sid)['learning']['skills']['arm']['attempts']


def test_validation_regression_blocks_train_score_optimization():
 from game.learning import progress
 before={'passed':False,'guards_pass':True,'score':1,'cases':[{'id':'v','split':'validation','score':2}]}
 after={'passed':False,'guards_pass':True,'score':4,'cases':[{'id':'v','split':'validation','score':.5}]}
 assert progress(before,after,.001)==(False,True)


def test_partial_metric_failure_returns_a_failed_receipt_instead_of_crashing():
 w=world();c=skill();c['metrics'].append({'name':'bad','expression':"s['missing']",'reduce':'last'});setplan(w,[c]);r=assess(w,'arm')
 assert not r['passed'] and all('error' in row for row in r['cases'])


def test_real_foot_support_is_distinct_from_generic_limb_contact():
 from game.living import sensors
 w=world();w['contacts']={'joints':['left_foot'],'support':['right_toe']}
 s=sensors(w);assert s['contacts']['left_foot'] and not s['support']['left_foot'] and s['support']['right_toe']


def test_autonomous_scheduler_stops_before_starting_more_paid_turns_on_mastery(tmp_path):
 from types import SimpleNamespace
 from threading import Lock
 from game.life import LifeRuntime
 path,sid=setup_store(tmp_path)
 with GameStore(path) as game:
  with game.mutation(sid) as w:
   define(w,program(.25));record(w,'arm',assess(w,'arm'),applied=True)
   w['life'].update(running=True,iteration=1,limit=10)
 calls=[]
 app=SimpleNamespace(config=SimpleNamespace(database=path),_lock=Lock(),_runs={},_session_busy=lambda _:False,start_run=lambda *args:calls.append(args))
 runtime=LifeRuntime(app);runtime._active.add(sid);runtime.step(sid)
 assert not calls
 with GameStore(path) as game:
  w=game.get(sid);assert w['life']['limit']==1 and w['life']['status']=='goal_passed' and w['life']['running']


def test_active_plan_cannot_be_bypassed_by_omitting_skill_after_plateau(tmp_path):
 path,sid=setup_store(tmp_path)
 with GameStore(path) as game:
  with game.mutation(sid) as w:
   w['learning']['skills']['arm']['plateau_limit']=2
   for _ in range(2):record(w,'arm',assess(w,'arm'),applied=False)
 with pytest.raises(ValueError,match='no ready'):iterate(path,sid,{'objective':'Bypass','changes':[program(.3)],'play':False})


def test_domain_neutral_grader_requires_measured_file_and_test_results():
 from game.learning import grade_report
 c={'score':"r['metrics']['files_ok']",'success':"r['metrics']['files_ok']==3 and r['metrics']['tests_failed']==0",'guards':["r['verified_inputs']"],
    'metrics':[{'name':'files_ok','target':{'min':3}},{'name':'tests_failed','target':{'max':0}}]}
 assert not grade_report(c,{'passed':True,'verified_inputs':True,'metrics':{'files_ok':2,'tests_failed':0}})['passed']
 assert grade_report(c,{'passed':True,'verified_inputs':True,'metrics':{'files_ok':3,'tests_failed':0}})['passed']
 assert not grade_report(c,{'passed':True,'verified_inputs':False,'metrics':{'files_ok':3,'tests_failed':0}})['passed']


def test_compile_error_preserves_bad_working_source_for_next_debug_iteration(tmp_path):
 path,sid=setup_store(tmp_path);bad={**program(.2),'files':{'main.js':'module.exports = ???'}}
 r=iterate(path,sid,{'objective':'Bad syntax','skill':'arm','changes':[bad],'play':False})
 assert not r['published'] and 'build:' in r['fitness']['error']
 with GameStore(path) as game:
  w=game.get(sid);assert w['learning']['skills']['arm']['working']['files']['main.js']=='module.exports = ???'
  assert w['projects']['arm']['files']['main.js']==CODE


def test_autonomous_practice_cannot_weaken_criteria_or_relabel_the_human_goal():
 w=world();setplan(w);record(w,'arm',assess(w,'arm'),applied=True);w['life']['run_kind']='autonomous'
 weak=skill();weak['metrics'][0]['target']['min']=0
 with pytest.raises(ValueError,match='criteria are locked'):setplan(w,[weak])
 args={'action':'plan','goal':'New easy goal','target':'arm','reason':'skip','skills':[skill()]}
 with pytest.raises(ValueError,match='goal/target is locked'):plan(w,args)
 # Refining the dependency graph remains possible without moving the success bar.
 c=skill();c['depends']=['prerequisite'];setplan(w,[skill('prerequisite'),c])
 assert summary(w)['focus']=='prerequisite'


def test_optional_walking_contract_example_is_valid_and_not_installed_by_default():
 from pathlib import Path
 w=world();assert not w['learning']['goal']
 args=json.loads((Path(__file__).parents[1]/'game/WALKING_FITNESS.json').read_text());plan(w,args)
 assert summary(w)['focus']=='balance'
 assert not assess(w,'balance')['passed']  # No controller supplied by the example.


def test_manual_web_evaluation_is_version_bound_and_uses_no_model_calls(tmp_path):
 from dagi_core.web import WebApp
 from test_core_web import _config,_start,_stop,_request
 app=WebApp(_config(tmp_path),provider_factory=lambda *_:pytest.fail('manual evaluation must not call a model'))
 server,thread,base=_start(app)
 try:
  _,_,raw=_request(base+'/api/game/sessions','POST',{});sid=json.loads(raw)['session_id']
  with GameStore(app.config.database) as game:
   with game.mutation(sid) as w:
    define(w,program(.25));setplan(w);contract=w['learning']['skills']['arm']['version'];version=w['version']
  payload={'skill':'arm','contract':contract,'world_version':version}
  status,_,raw=_request(f'{base}/api/game/sessions/{sid}/learning/evaluate','POST',payload)
  result=json.loads(raw);assert status==200 and result['local'] and result['model_calls']==0 and result['attempt']['passed']
  from urllib.error import HTTPError
  with pytest.raises(HTTPError) as error:_request(f'{base}/api/game/sessions/{sid}/learning/evaluate','POST',{**payload,'world_version':999})
  assert error.value.code==400
  with closing(StateStore(app.config.database)) as state:assert state.list_runs(sid)==[]
 finally:_stop(server,thread)


def test_rechecking_a_prerequisite_requires_a_fresh_composition_receipt():
 w=world();define(w,program(.25));setplan(w,[skill(),skill('composed',['arm'])],target='composed')
 record(w,'arm',assess(w,'arm'),applied=True);record(w,'composed',assess(w,'composed'),applied=True)
 assert summary(w)['status']=='mastered'
 record(w,'arm',assess(w,'arm'),applied=True)
 assert summary(w)['status']=='training' and summary(w)['focus']=='composed'
