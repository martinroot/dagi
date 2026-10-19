"""Initial film arrangement only. All subsequent movement uses authored muscles."""
from __future__ import annotations
import math
from pathlib import Path


def arrange(world,root=.8,hip_angle=1.7,knee=-1.2,ankle=-1.3):
    """Forward kinematics for a new folded actor, never a playback teleport."""
    from .character import anchors
    c=world['character'];nodes=world['nodes']
    def put(k,p):nodes[k]={'x':p[0],'y':p[1],'px':p[0],'py':p[1]}
    def along(p,l,a):return(p[0]+math.cos(a)*l,p[1]+math.sin(a)*l)
    put('hip',(500,470));put('neck',along((500,470),-c['bones']['hip']['length'],root));put('head',along((nodes['neck']['x'],nodes['neck']['y']),-c['neck_length'],root))
    center=along((500,470),-c['bones']['hip']['length']/2,root)
    for k,(u,v) in anchors(c).items():put(k,(center[0]+math.cos(root)*u-math.sin(root)*v,center[1]+math.sin(root)*u+math.cos(root)*v))
    for side in ('left','right'):
        for names,start,angles in [(['elbow','hand'],'shoulder',[math.pi/2-root,0]),(['knee','foot','toe'],'pelvis',[hip_angle,knee,ankle])]:
            a=root;p=(nodes[side+'_'+start]['x'],nodes[side+'_'+start]['y'])
            for name,angle in zip(names,angles):
                a+=angle;p=along(p,c['bones'][side+'_'+name]['length'],a);put(side+'_'+name,p)
    bottom=max(p['y']+(c['head_radius'] if k=='head' else c['bones'].get(k,{'radius':0})['radius']) for k,p in nodes.items())
    for p in nodes.values():p['y']+=536-bottom;p['py']+=536-bottom
    world['articulation']={};world['muscle_state']={};world['dynamics']={}


def install(world):
    from .workshop import initialize_physical,edit
    from .character import edit as character_edit
    from .director import define
    initialize_physical(world);world['physics_engine']='chipmunk';world['gravity']=981
    edit(world,{'operation':'body_control','values':{'mode':'physical','stage_rig':False,'self_collision':False,'muscle_scale':6,'muscle_dynamics':False,'solver_substeps':4}})
    character_edit(world,{'operation':'character','values':{'name':'Dagi / Matter','style':'sticks','head_radius':16,'head_mass':.7,'bones':{s+'_toe':{'length':24,'radius':5.5,'mass':.35} for s in ('left','right')},'surface':{'skin':'#c28b71','muscle':'#a35e58','bone':'#f1e8d3','accent':'#3e8f89','eye':'#203f45','roughness':.58,'metallic':0,'head_width':.93,'outline':.45,'muscles':.85,'markings':0},'features':{'hair':'swept','hair_length':.55,'hair_color':'#243942','iris':'#499e8d','detail':1,'eye_size':1.05,'freckles':.12}}})
    arrange(world)
    edit(world,{'operation':'environment','values':{'sky_top':'#ffffff','sky_bottom':'#ffffff','ground_top':'#ffffff','ground_bottom':'#ffffff','sun':{'x':740,'y':110,'radius':0,'color':'#ffffff'},'clouds':[],'mountains':[]}})
    character_edit(world,{'operation':'art','values':{'key':{'x':260,'y':60,'color':'#fff1d9','intensity':.85},'ambient':.7,'shadow':.22,'rim':.25,'exposure':1,'vignette':0,'grain':0,'atmosphere':{'depth':0,'haze':0,'vegetation':0,'wind':.2}}})
    files=Path(__file__).with_name('examples')
    define(world,{'name':'Matter / Dagi','description':'Authored physical film: folded skeleton, internal muscles, free flight. No stage rig or model calls.','entry':'matter.js','files':{name:(files/name).read_text() for name in ('matter.js','body-controller.js','story-kit.js')}})
    world['life'].update(status='paused',intent='MATTER · внутренние мышцы · свободный полёт · без страховки')
    return world
