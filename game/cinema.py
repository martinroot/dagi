"""Bounded presentation channels and an explicit, opt-in powered stage rig.

Authored shots never write physics coordinates. The rig applies finite forces
and torques to a dynamic torso through the ordinary collision solver. It is an
external aid, counted by skill guards, and cannot certify unassisted locomotion.
"""
from __future__ import annotations
import copy
import json
import math
from pathlib import Path

HELP = {
    "story":"Author a project with multiple CommonJS files. The optional story-kit.js provides sample(track,t), sequence(clips,t) and easing; the same server t drives camera, face, look, speech and control. Tracks are data authored by the agent, not a fixed catalogue of activities. Read game/examples/story-kit.js and game/examples/hello-dagi.js via view=source. The packaged premiere is an explicitly scripted, stage-assisted film, not a learned skill. Start a separate film from the UI; clean sessions remain empty.",
    "look":"Project return look:{character?:{style?,surface?:partial_surface,features?:partial_features},art?:partial_art,environment?:partial_environment,reveal?:{progress:0..1,band:8..100,color:'#RRGGBB'}}. Presentation only, resets when omitted, no body dimensions/colliders or gravity edits. reveal sweeps upward across the live body and scenery; repeated ramps create looping material transformations. Static art layers remain separate. Features: hair:'none'|'crop'|'swept'|'spiky'|'bob',hair_color,iris,brow,lips:'#RRGGBB'; hair_length,detail,freckles:0..1; eye_size:.7..1.3. Cosmetics never change physical certificates.",
    "face":"expression adds blink_left,blink_right,smile,brow,clench:0..1. Independent eyelids allow a wink; existing valence,arousal,focus,surprise,mouth,squint,tilt,gaze remain. Facial cues are authored animation, not subjective feelings.",
    "speech":"Project return speech:{text:'Hello I’m Dagi',speaker?:'DAGI',progress?:0..1,opacity?:0..1,color?:'#RRGGBB'}. Screen-readable vector bubble follows the actual head; wraps text and clamps inside the shot. progress reveals Unicode characters. No HTML or network assets.",
    "camera":"camera zoom .65..10; target joint/object/[x,y],offset,ease,shake,letterbox; optional cut:true applies immediately. Smooth tracks should use eased numeric keyframes with cut:true to sample exactly; ordinary camera output still damps. Reduced-motion viewer limits zoom/shake and transformation pulses.",
    "rig":"Enable explicitly with body_control{values:{stage_rig:true}}. Then control.rig:{position:[x,y] (desired hip),angle:-30..30 (unwrapped torso radians),weight?:0..1,stiffness?:0..3000,damping?:0..1000,rotation_stiffness?:0..400000,rotation_damping?:0..60000}. Bounded external force <=70000 per axis, torque <=600000; dynamic collision solver, no teleport. Omit/weight0 to release; no hidden standing aid. Positive rig work is separate energy.stage_work. UI always labels the powered stage aid; r.external_supports includes it, even while released. Use internal relative servos for limbs. Film assistance does not count as unassisted skill mastery.",
}


def validate_look(world, value):
    from .world import keys, number
    from .character import edit as character_edit, DEFAULT, ART
    from .workshop import edit as workshop_edit, color
    keys(value,("character","art","environment","reveal"))
    if len(json.dumps(value))>14000:raise ValueError("look exceeds14KB")
    if "character" in value:
        keys(value["character"],("style","surface","features"))
        temporary={"character":copy.deepcopy(world.get("character") or DEFAULT)}
        character_edit(temporary,{"operation":"character","values":value["character"]})
    if "art" in value:
        keys(value["art"],set(ART)-{"layers"})
        temporary={"art":copy.deepcopy(world.get("art") or ART)}
        character_edit(temporary,{"operation":"art","values":value["art"]})
    if "environment" in value:
        temporary={"environment":world.get("environment")}
        workshop_edit(temporary,{"operation":"environment","values":value["environment"]})
    if "reveal" in value:
        r=value["reveal"];keys(r,("progress","band","color"))
        number(r.get("progress"),0,1,"reveal progress");number(r.get("band",30),8,100,"reveal band");color(r.get("color","#aaf5e4"))
    return copy.deepcopy(value)


def validate_speech(value):
    from .world import keys,number,text
    from .workshop import color
    keys(value,("text","speaker","progress","opacity","color"))
    text(value.get("text"),180,"speech text")
    text(value.get("speaker","DAGI"),32,"speaker")
    for k in ("progress","opacity"):number(value.get(k,1),0,1,k)
    color(value.get("color","#aef3df"))
    return copy.deepcopy(value)


def validate_rig(world, value):
    from .world import keys,number
    if not world["body_control"].get("stage_rig",False):raise ValueError("rig requires explicit body_control.stage_rig:true")
    if world.get("physics_engine")!="chipmunk" or world["body_control"]["mode"]!="physical":raise ValueError("stage rig requires physical Chipmunk body")
    keys(value,("position","angle","weight","stiffness","damping","rotation_stiffness","rotation_damping"))
    p=value.get("position")
    if not isinstance(p,list) or len(p)!=2:raise ValueError("rig position is [x,y]")
    for v in p:number(v,40,960,"rig coordinate")
    number(value.get("angle"),-30,30,"rig angle")
    for k,d,lo,hi in (("weight",1,0,1),("stiffness",1600,0,3000),("damping",250,0,1000),("rotation_stiffness",250000,0,400000),("rotation_damping",25000,0,60000)):
        number(value.get(k,d),lo,hi,k)


def apply_rig(sim, value, dt):
    if not value or not sim.world["body_control"].get("stage_rig"):return
    import pymunk
    weight=value.get("weight",1)
    torso=sim.segments["hip"][0];hip=torso.local_to_world(sim.ends["hip"][1])
    total=sum(b.mass for b in sim.space.bodies if b.body_type==pymunk.Body.DYNAMIC and b not in sim.objects.values())
    force=(pymunk.Vec2d(*value["position"])-hip)*value.get("stiffness",1600)-torso.velocity*value.get("damping",250)+pymunk.Vec2d(0,-total*sim.world['gravity'])
    force=pymunk.Vec2d(max(-70000,min(70000,force.x)),max(-70000,min(70000,force.y)))*weight
    torque=max(-600000,min(600000,(value['angle']-torso.angle)*value.get('rotation_stiffness',250000)-torso.angular_velocity*value.get('rotation_damping',25000)))*weight
    torso.apply_force_at_world_point(force,torso.position);torso.torque+=torque
    work=max(0,force.dot(torso.velocity))+max(0,torque*torso.angular_velocity)
    sim.world['energy']['stage_work']=sim.world['energy'].get('stage_work',0)+work*dt/10000


def premiere(world,physical=False):
    """Install authored example only in a newly requested, dedicated session."""
    if physical:
        from .physical_film import install
        return install(world)
    from .workshop import edit
    from .character import edit as character_edit, initialize
    from .director import define
    if world.get("environment") is None:edit(world,{"operation":"environment","values":{}})
    initialize(world)
    edit(world,{"operation":"body_control","values":{"mode":"physical","self_collision":False,"stage_rig":True,"muscle_scale":3}})
    character_edit(world,{"operation":"character","values":{"name":"Dagi","style":"ceramic","head_radius":17,"head_mass":.7,"surface":{"bone":"#e0e8e3","accent":"#62d8bd","eye":"#183d48","head_width":1,"metallic":.3,"outline":.45},"features":{"detail":1,"hair":"swept","hair_length":.8,"hair_color":"#17394b","iris":"#61cbb8"}}})
    # Explicit initial arrangement of a fresh film set, never a live reset.
    dx=500-world['nodes']['hip']['x'];dy=447-world['nodes']['hip']['y']
    for p in world['nodes'].values():
        p.update(x=p['x']+dx,y=p['y']+dy,px=p['x']+dx,py=p['y']+dy)
    edit(world,{"operation":"environment","values":{"sky_top":"#132a44","sky_bottom":"#6c9c9d","ground_top":"#4d7979","ground_bottom":"#142c41","sun":{"x":740,"y":140,"radius":30,"color":"#f4dbab"},"clouds":[{"x":200,"y":100,"scale":.9},{"x":820,"y":160,"scale":1.3}]}})
    character_edit(world,{"operation":"art","values":{"key":{"x":250,"y":80,"color":"#bdeee5","intensity":1.3},"ambient":.6,"rim":.8,"grain":.025,"vignette":.24,"atmosphere":{"depth":.8,"vegetation":.6,"haze":.35,"wind":.2}}})
    folder=Path(__file__).with_name('examples')
    define(world,{"name":"Hello Dagi","description":"Authored 38-second film · powered stage rig · no model calls","entry":"hello-dagi.js","files":{p.name:p.read_text() for p in folder.glob('*.js')}})
    world['life'].update(status='paused',intent='Первый мультфильм · нажмите «Смотреть» · без API')
    return world
