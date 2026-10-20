"""Conservation and contact tests: no aesthetic or learned-skill certification."""
from copy import deepcopy
import math
import pytest
from game.workshop import initialize_physical

def install(w):
    initialize_physical(w)
    w['gravity']=981
    return w

from game.world import fresh_world
from game.rigid import RigidSimulator
from game.living import advance,sensors
from game.learning import supports




def test_relative_pd_muscle_is_recomputed_on_each_solver_substep():
    w=install(fresh_world(1));sim=RigidSimulator(w);system=sim.muscle_system
    system.prepare({'servos':{'left_hand':{'angle':-.2,'stiffness':10000,'damping':0}}})
    system.apply();before=system.torques['left_hand']
    system.joints['left_hand'][1].angle+=.1
    system.apply();assert system.torques['left_hand']==pytest.approx(before-1000)


def flying():
    w=install(fresh_world(1));w['active_project']=None
    for p in w['nodes'].values():
        p['y']-=220;p['py']=p['y']+200/60;p['px']=p['x']-40/60
    return w


def test_active_internal_muscles_cannot_steer_the_center_of_mass_in_flight():
    w=flying();w['body_control']['solver_substeps']=8;sim=RigidSimulator(w);initial=deepcopy(w['dynamics'])
    for i in range(30):sim.step({'muscles':{'left_knee':.3,'right_foot':-.2,'left_hand':.2}})
    d=w['dynamics'];assert d['airborne'] and d['contact_impulse']==0
    assert d['velocity'][0]==pytest.approx(initial['velocity'][0],abs=.1)
    assert d['velocity'][1]-initial['velocity'][1]==pytest.approx(981*.5,abs=.3)
    assert abs(d['angular_momentum']-initial['angular_momentum'])<150
    assert w['energy']['muscle_work']>0 and w['energy'].get('stage_work',0)==0


def test_slow_motion_reduces_integrated_time_without_changing_gravity_or_velocity_units():
    w=flying();sim=RigidSimulator(w);initial=deepcopy(w['dynamics'])
    for _ in range(60):advance(w,1,simulator=sim,diagnostics=False,time_scale=.25)
    assert w['tick']==15 and w['dynamics']['solver_dt']==pytest.approx(1/240)
    assert w['gravity']==981
    assert w['dynamics']['velocity'][1]-initial['velocity'][1]==pytest.approx(981*.25,abs=.1)
    assert sensors(w)['vy']==pytest.approx(sim.ends['hip'][0].velocity_at_world_point(sim.ends['hip'][0].local_to_world(sim.ends['hip'][1])).y)






def test_authored_heel_extends_real_contact_geometry_not_only_appearance():
    from game.character import edit
    w=install(fresh_world(1))
    edit(w,{'operation':'character','values':{'bones':{'right_toe':{'heel':9}}}})
    sim=RigidSimulator(w);body,length,_,_=sim.segments['right_toe']
    shape=next(s for s in body.shapes if hasattr(s,'a'))
    assert shape.a.x==-length/2-9
    assert body.moment>0 and w['character']['bones']['right_toe']['heel']==9
