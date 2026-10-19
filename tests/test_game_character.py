"""Morphology has physical consequences; visual authoring remains declarative."""
from copy import deepcopy
import math
import time
import pytest
from game.character import edit,reshape
from game.director import validate_draw
from game.rigid import RigidSimulator
from game.studio import build,activate,configuration,digest
from game.living import trial
from game.world import fresh_world,upgrade,links
from game.workshop import initialize_physical


def character():
 w=fresh_world(1);initialize_physical(w);w['physics_engine']='chipmunk';return w


def test_anatomical_anchors_belong_to_torso_and_lengths_masses_reach_solver():
 w=character();edit(w,{'operation':'character','values':{'shoulder_width':38,'hip_width':24,'head_radius':15,'head_mass':2,'bones':{'right_elbow':{'length':47,'radius':8,'mass':1.8}}}})
 sim=RigidSimulator(w);body,length,_,_=sim.segments['right_elbow']
 assert length==pytest.approx(47) and body.mass==1.8
 assert next(iter(body.shapes)).radius==8
 assert sim.ends['left_shoulder'][0] is sim.segments['hip'][0]
 assert sim.ends['right_shoulder'][0] is sim.segments['hip'][0]
 assert math.dist(tuple(sim.ends['left_shoulder'][0].local_to_world(sim.ends['left_shoulder'][1])),tuple(sim.ends['right_shoulder'][0].local_to_world(sim.ends['right_shoulder'][1])))==pytest.approx(38)
 assert next(iter(sim.ends['head'][0].shapes)).radius==15
 assert sim.ends['head'][0].mass==2
 assert sim.springs=={}
 assert ('left_shoulder','left_elbow') in links(w)


def test_style_edit_preserves_pose_and_does_not_install_motion():
 w=character();nodes=deepcopy(w['nodes']);edit(w,{'operation':'character','values':{'style':'anatomical','surface':{'skin':'#bca78a','muscles':1}}})
 assert w['nodes']==nodes and not w['active_project'] and not w['active_policy']
 assert w['character']['surface']['bone']=='#eee2cb'
 r=trial(w);assert r['passed'] and r['muscle_work']==0 and r['upright_ratio']<.5


def test_morphing_a_fallen_body_preserves_link_direction_and_head_pivot():
 w=character();sim=RigidSimulator(w)
 for _ in range(120):sim.step({})
 old=deepcopy(w['nodes']);edit(w,{'operation':'character','values':{'bones':{'right_hand':{'length':43}}}})
 a,b=w['nodes']['right_elbow'],w['nodes']['right_hand'];oa,ob=old['right_elbow'],old['right_hand']
 assert math.dist((a['x'],a['y']),(b['x'],b['y']))==pytest.approx(43)
 assert math.atan2(b['y']-a['y'],b['x']-a['x'])==pytest.approx(math.atan2(ob['y']-oa['y'],ob['x']-oa['x']))
 sim=RigidSimulator(w);head=sim.ends['head'][0];neck=sim.ends['neck'][0].local_to_world(sim.ends['neck'][1]);attachment=head.local_to_world((0,w['character']['neck_length']))
 assert (attachment-neck).length<1e-6


def test_legacy_saved_world_is_not_reshaped_on_read():
 w=fresh_world(1);w.pop('character');w.pop('art');before=deepcopy(w['nodes']);upgrade(w)
 assert w['character'] is None and w['art'] is None and w['nodes']==before
 edit(w,{'operation':'character','values':{'name':'Converted','style':'ceramic'}})
 assert 'left_shoulder' in w['nodes'] and 'right_toe' in w['nodes']


@pytest.mark.parametrize('values',[{'bones':{'hand':{'length':10}}},{'head_radius':100},{'surface':{'skin':'red'}},{'style':'image'},{'bones':{'hip':{'mass':float('nan')}}}])
def test_invalid_anatomy_rejected(values):
 with pytest.raises(ValueError):edit(character(),{'operation':'character','values':values})


GRAD={'type':'linear','from':[0,0],'to':[20,40],'stops':[[0,'#ffddaa'],[1,'#335577']]}
CURVE={'type':'bezier','segments':[['M',0,0],['C',10,0,20,10,20,20],['Q',10,30,0,20],['Z']],'fill':GRAD,'blend':'multiply','transform':[1,0,0,1,50,50],'shadow':{'color':'#223344','blur':4,'x':2,'y':3}}


def test_gradient_bezier_layers_validate_and_roundtrip_configuration():
 w=character();edit(w,{'operation':'art','values':{'mode':'toon','key':{'color':'#ffeeaa'},'layers':[{'id':'curve','depth':-2,'parallax':.3,'commands':[CURVE]}]}})
 assert w['art']['key']['x']==180
 assert configuration(w)['art']['layers'][0]['commands'][0]['fill']==GRAD
 assert validate_draw([CURVE])==[CURVE]


@pytest.mark.parametrize('change',[{'fill':{'type':'linear','from':[0,0],'to':[1,1],'stops':[[.8,'#ffffff'],[.2,'#000000']]}},{'segments':[['M',0,0],['C',1,2]]},{'transform':[1,0]},{'shadow':{'color':'url(file)','blur':2}},{'blend':'arbitrary'},{'fill':'url(https://example.com)'}])
def test_invalid_vector_resources_and_geometry_are_rejected(change):
 with pytest.raises(ValueError):validate_draw([{**CURVE,**change}])


def test_vector_layer_budgets_and_duplicate_ids():
 w=character();layer={'id':'a','commands':[CURVE]}
 with pytest.raises(ValueError,match='duplicate'):edit(w,{'operation':'art','values':{'layers':[layer,layer]}})
 with pytest.raises(ValueError):edit(w,{'operation':'art','values':{'background':{'asset':'raster'}}})
 assert not any(k in w['art'] for k in ('background','images','assets'))


def test_publication_remaps_latest_live_pose_not_trial_seed():
 w=character();build(w,{'operation':'begin','objective':'Longer forearm'})
 build(w,{'operation':'edit','changes':[{'operation':'character','values':{'bones':{'right_hand':{'length':46}}}}]})
 build(w,{'operation':'test'});assert w['draft']['report']['passed']
 build(w,{'operation':'commit'})
 sim=RigidSimulator(w)
 for _ in range(90):sim.step({})
 hip=deepcopy(w['nodes']['hip']);tick=w['tick'];w['draft']['activate_at']=0;id=w['draft']['id'];activate(w,{'id':id})
 assert w['tick']==tick
 a,b=w['nodes']['right_elbow'],w['nodes']['right_hand']
 assert math.dist((a['x'],a['y']),(b['x'],b['y']))==pytest.approx(46)
 assert w['nodes']['hip']['x']==pytest.approx(hip['x'])
 assert w['nodes']['head']['y']>450  # Must not stand up on publication.


def test_cosmetic_changes_do_not_rebuild_live_solver_or_erase_angular_momentum(tmp_path):
 from contextlib import closing
 from dagi_core.state import StateStore
 from game.store import GameStore,enable_live,disable_live,live_slot,clock_tick
 path=tmp_path/'state.db'
 with closing(StateStore(path)) as state:sid=state.create_session()
 enable_live(path)
 try:
  with GameStore(path) as game:
   game.create(sid);slot=live_slot(path,sid);sim=slot.simulator
   sim.segments['right_hand'][0].angular_velocity=1.25
   game.apply(sid,edit,{'operation':'character','values':{'style':'ceramic','surface':{'skin':'#bb9966'}}})
   assert slot.simulator is sim
   assert sim.segments['right_hand'][0].angular_velocity==1.25
   assert sim.world['character']['style']=='ceramic'
 finally:disable_live(path)


def test_bone_error_uses_authored_lengths_and_torso_attachment_points():
 w=character();w['gravity']=0
 edit(w,{'operation':'character','values':{'bones':{'right_hand':{'length':55}}}})
 r=trial(w,frames=12)
 assert r['passed'] and r['max_bone_error']<.5
