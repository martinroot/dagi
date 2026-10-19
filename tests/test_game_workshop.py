"""Physical outcomes of generic constructions; these fixtures are not installed scenes."""
from contextlib import closing
from copy import deepcopy
import json
import math
import time

import pytest

from dagi_core.state import StateStore
from dagi_core.web import WebApp
from game.embodiment import validate
from game.living import advance,trial,sensors
from game.mechanics import Mechanics
from game.rigid import RigidSimulator
from game.store import GameStore
from game.studio import build,activate,configuration,digest,validate_widget
from game.workshop import initialize_physical,body,joint,edit
from game.world import fresh_world
from test_core_web import _config,_request,_start,_stop


def physical():
    w=fresh_world(1);w['physics_engine']='chipmunk';initialize_physical(w);return w


def add(w,**kw):body(w,{'operation':'body','body':kw})
def connect(w,**kw):joint(w,{'operation':'joint','joint':kw})
def rope(w,**kw):edit(w,{'operation':'rope','rope':kw})


def test_new_uncontrolled_body_falls_has_ankles_and_consumes_no_muscle_work():
    w=physical();sim=RigidSimulator(w)
    assert sim.springs=={} and len(sim.muscle_system.joints)==11
    assert 'left_toe' in w['nodes']
    assert all(c.a is not sim.space.static_body and c.b is not sim.space.static_body for c in sim.space.constraints)
    report=trial(w)
    assert report['passed'] and report['mode']=='physical'
    assert report['upright_ratio']<.4 and report['muscle_work']==0


@pytest.mark.parametrize('output',[{'drive':1},{'jump':True},{'pose':{'head':[0,-78]}},{'forces':{'hip':[100,0]}},{'object_forces':{'anything':[1,0]}},{'appendage_pose':{'x':1}}])
def test_physical_body_rejects_predefined_walking_and_unaccounted_forces(output):
    with pytest.raises(ValueError,match='physical mode'):validate(physical(),output)


def test_muscle_torque_has_equal_opposite_reaction_and_changes_actual_angle():
    a=physical();b=deepcopy(a);sim=RigidSimulator(b)
    sim.muscle_system.prepare({'muscles':{'right_hand':.7}})
    sim.muscle_system.apply()
    parent,arm,*_=sim.muscle_system.joints['right_hand']
    assert abs(parent.torque+arm.torque)<1e-6 and arm.torque>0
    sim=RigidSimulator(b)
    for _ in range(30):sim.step({'muscles':{'right_hand':.7}})
    advance(a,30)
    assert abs(a['articulation']['right_hand']['angle']-b['articulation']['right_hand']['angle'])>.15
    assert b['energy']['muscle_work']>0


def test_relative_joint_limits_and_servos_do_not_restore_global_stance():
    w=physical();sim=RigidSimulator(w)
    for _ in range(180):sim.step({'servos':{'right_hand':{'angle':1,'max_torque':15000}}})
    assert w['nodes']['head']['y']>480
    for j in w['articulation'].values():assert j['min']-.3<=j['angle']<=j['max']+.3
    with pytest.raises(ValueError):validate(w,{'servos':{'right_hand':{'angle':9}}})


def test_material_density_friction_and_static_polygons_reach_the_solver():
    w=physical()
    for name,material,x in [('light','wood',500),('heavy','steel',600)]:add(w,id=name,shape='rect',x=x,y=100,width=50,height=30,material=material)
    assert w['objects'][1]['mass']>w['objects'][0]['mass']*10
    add(w,id='terrain',shape='polygon',x=600,y=450,vertices=[[-100,30],[100,30],[60,-20]],motion='static',material='stone')
    sim=RigidSimulator(w);sim.step({})
    assert sim.objects['terrain'].body_type==sim.objects['terrain'].STATIC
    shape=next(iter(sim.objects['heavy'].shapes));assert shape.friction==.5
    with pytest.raises(ValueError):add(w,id='bad',shape='polygon',x=400,y=100,vertices=[[0,0],[30,0],[10,10],[30,30],[0,30]])


def test_rope_supports_mass_transmits_tension_and_breaks_when_overloaded():
    for strength,expected in [(50000,False),(100,True)]:
        w=physical();add(w,id='load',shape='circle',x=600,y=300,radius=15,mass=1)
        rope(w,id='line',a='world',anchor_a=[600,100],b='load',points=[[600,100],[600,300]],break_force=strength)
        advance(w,240)
        assert w['rope_frames'][0]['broken'] is expected
        if expected:assert w['objects'][0]['y']>500
        else:assert w['objects'][0]['y']<310 and w['rope_frames'][0]['tension']>100
        # A physical rebuild preserves a broken rope and actual link geometry.
        before=deepcopy(w['rope_state']);RigidSimulator(w)
        assert w['rope_state']==before


def test_rope_can_attach_to_a_real_hand_and_a_body():
    w=physical();add(w,id='weight',shape='circle',x=300,y=440,radius=8,mass=.2)
    rope(w,id='tie',a='self:right_hand',b='weight',points=[[210,436],[255,410],[300,440]])
    sim=RigidSimulator(w);r=sim.mechanics.ropes['tie']
    assert r['joints'][0].a is sim.ends['right_hand'][0]
    for _ in range(60):sim.step({'muscles':{'right_hand':.3}})
    assert len(w['rope_frames'][0]['segments'])>3 and w['energy']['muscle_work']>0


def test_unequal_weights_route_around_a_pulley_and_lift_the_lighter_mass():
    w=physical()
    for name,x,mass in [('left',520,.5),('right',620,2)]:add(w,id=name,shape='circle',x=x,y=400,radius=15,mass=mass)
    add(w,id='wheel',shape='circle',x=570,y=200,radius=35,mass=3)
    connect(w,id='axle',type='pivot',a='world',b='wheel',anchor=[570,200])
    rope(w,id='line',a='left',b='right',points=[[520,400],[520,200],[540,155],[600,155],[620,200],[620,400]],segment_length=10)
    advance(w,90)
    left,right,wheel=w['objects']
    assert left['y']<370 and right['y']>450
    assert abs(wheel['x']-570)<1 and abs(wheel['y']-200)<1
    assert not w['rope_frames'][0]['broken']


def car(w):
    add(w,id='chassis',shape='rect',x=650,y=440,width=130,height=20,mass=3,material='wood')
    for name,x,offset in [('wheel-a',610,-40),('wheel-b',690,40)]:
        add(w,id=name,shape='circle',x=x,y=480,radius=22,mass=1,material='rubber')
        connect(w,id='axle-'+name,type='pivot',a='chassis',b=name,anchor_a=[offset,40])
        connect(w,id='motor-'+name,type='motor',a='chassis',b=name,rate=-5,max_force=25000)


def test_generic_wheel_assembly_moves_via_ground_friction_and_records_motor_work():
    w=physical();car(w);advance(w,180)
    assert w['objects'][0]['x']>730 and w['energy']['motor_work']>0
    assert w['energy']['muscle_work']==0
    assert abs((w['objects'][2]['x']-w['objects'][1]['x'])-80)<5
    with pytest.raises(ValueError):validate(w,{'joint_controls':{'motor-wheel-a':{'max_force':999999}}})


def test_gear_constraint_couples_rotation_and_motor_controls_preserve_authored_caps():
    w=physical()
    for name,x in [('a',500),('b',600)]:
        add(w,id=name,shape='circle',x=x,y=200,radius=20,mass=1)
        connect(w,id='pivot-'+name,type='pivot',a='world',b=name,anchor=[x,200])
    connect(w,id='drive',type='motor',a='world',b='a',rate=2,max_force=12000)
    connect(w,id='gear',type='gear',a='a',b='b',ratio=-2)
    sim=RigidSimulator(w)
    for _ in range(120):sim.step({'joint_controls':{'drive':{'rate':4,'max_force':10000}}})
    assert abs(sim.objects['a'].angular_velocity+2*sim.objects['b'].angular_velocity)<.1
    assert abs(sim.objects['a'].angular_velocity)>2
    assert w['mechanisms'][2]['max_force']==12000


def test_removing_a_connected_body_removes_its_rope_and_mechanism():
    from game.director import anatomy
    w=physical();add(w,id='load',shape='circle',x=500,y=300,radius=12)
    rope(w,id='line',a='world',anchor_a=[500,100],b='load',points=[[500,100],[500,300]])
    connect(w,id='spring',type='spring',a='world',anchor_a=[500,100],b='load',length=200)
    anatomy(w,{'operation':'remove_body','id':'load'})
    assert not w['objects'] and not w['mechanisms'] and not w['ropes']


def test_environment_and_icon_skill_are_authorable_without_installing_a_story():
    w=physical();edit(w,{'operation':'environment','values':{'sky_top':'#123456','clouds':[{'x':200,'y':90,'scale':1.2}]}})
    assert w['environment']['sky_top']=='#123456' and w['objects']==[]
    w['projects']['custom']={'description':'test'}
    skill={'id':'practice','kind':'skill','title':'Practice','icon':'🦾','hotkey':'1','x':700,'y':70,'width':200,'height':90,'target':{'type':'project','name':'custom','event':'practice'}}
    validate_widget(skill,w)
    with pytest.raises(ValueError):validate_widget({**skill,'hotkey':'F12'},w)


def test_body_angles_are_authored_configuration_and_material_update_keeps_new_coefficients():
    w=physical();add(w,id='beam',shape='rect',x=600,y=200,width=80,height=20,material='wood',angle=.3)
    first=digest(configuration(w));w['objects'][0]['angle']=1.2
    assert digest(configuration(w))==first
    w['objects'][0]['definition']['angle']=.6
    assert digest(configuration(w))!=first
    build(w,{'operation':'begin','objective':'change substance'})
    build(w,{'operation':'edit','changes':[{'operation':'substance','name':'wood','values':{'friction':1.2}}]});build(w,{'operation':'test'})
    assert w['draft']['report']['passed']
    w['draft'].update(state='scheduled',activate_at=0);activate(w,{'id':w['draft']['id']})
    assert w['objects'][0]['friction']==1.2


def test_new_web_session_is_unassisted_and_physics_can_run_without_a_saved_skill(tmp_path):
    app=WebApp(_config(tmp_path),provider_factory=lambda *_:None);server,thread,base=_start(app)
    try:
        _,_,raw=_request(base+'/api/game/sessions','POST',{});sid=json.loads(raw)['session_id']
        _,_,raw=_request(f'{base}/api/game/sessions/{sid}');data=json.loads(raw)
        assert data['body_control']['mode']=='physical' and data['scene']['active_project'] is None
        assert ['left_foot','left_toe'] in data['links'] or ('left_foot','left_toe') in data['links']
        _request(f'{base}/api/game/sessions/{sid}/life','POST',{'action':'play'})
        time.sleep(.2)
        with GameStore(app.config.database) as game:
            w=game.get(sid);assert w['tick']>0 and w['energy']['muscle_work']==0 and w['life']['limit']==0
        with closing(StateStore(app.config.database)) as state:assert state.list_runs(sid)==[]
    finally:_stop(server,thread)


def test_authored_mechanical_predicates_test_measured_motion_and_failed_check_rolls_back(tmp_path):
    from game.turns import iterate
    with closing(StateStore(tmp_path/'state.db')) as state:
        sid=state.create_session()
        with GameStore(state.path) as game:
            game.create(sid)
            with game.mutation(sid) as w:w['physics_engine']='chipmunk';initialize_physical(w)
        args={'objective':'Measure a falling load','play':False,'changes':[{'operation':'body','body':{'id':'load','shape':'circle','x':600,'y':200,'radius':12}}], 'verify':[{'label':'The load rises','expression':"r['objects']['load']['dy'] < -50"}]}
        failed=iterate(state.path,sid,args)
        assert not failed['published'] and not failed['verification'][0]['passed']
        with GameStore(state.path) as game:assert game.get(sid)['objects']==[]
        args['verify']=[{'label':'The load falls','expression':"r['objects']['load']['dy'] > 100 and r['muscle_work']==0"}]
        passed=iterate(state.path,sid,args)
        assert passed['published'] and passed['verification'][0]['passed']


def test_physical_grip_requires_a_nearby_surface_instead_of_remote_attachment():
    w=physical();add(w,id='remote',shape='circle',x=250,y=436,radius=8,mass=.2)
    sim=RigidSimulator(w);sim.step({'grip':{'object':'remote'}})
    assert w['contacts']['grip'] is None
    w=physical();add(w,id='near',shape='circle',x=223,y=436,radius=10,mass=.2)
    sim=RigidSimulator(w);sim.step({'grip':{'object':'near'}})
    assert w['contacts']['grip']=='near'
