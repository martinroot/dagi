"""General physical construction contracts. No machines or locomotion are supplied."""
from __future__ import annotations
import copy
import math
import re

SUBSTANCES = {
    "wood": {"density":650,"friction":.65,"restitution":.12,"color":"#ac8257"},
    "steel": {"density":7800,"friction":.5,"restitution":.08,"color":"#8395a8"},
    "stone": {"density":2600,"friction":.8,"restitution":.05,"color":"#8c9295"},
    "rubber": {"density":1100,"friction":1.4,"restitution":.55,"color":"#384651"},
}
BODY_CONTROL = {"mode":"assisted","muscle_scale":1,"air_damping":.999,"joint_damping":12,"self_collision":False}
ENVIRONMENT = {"sky_top":"#a9d4ee","sky_bottom":"#eff8ed","ground_top":"#9bb384","ground_bottom":"#597b67","sun":{"x":780,"y":105,"radius":38,"color":"#fff0ba"},"clouds":[],"mountains":[]}
DEFAULTS = {"body_control":BODY_CONTROL,"substances":SUBSTANCES,"ropes":[],"rope_frames":[],"rope_state":{},"mechanics_state":{},"articulation":{},"energy":{"muscle_work":0,"motor_work":0,"power":0},"environment":None,"character":None,"art":None}

HELP = {
 "body_control":"body_control {values:{mode:'physical'|'assisted',muscle_scale:.1..3,air_damping:.95..1,joint_damping:0..100,self_collision:bool}}. New browser sessions are physical. No automatic stance, drive, jump, pose or global limb springs in physical mode. Original assisted worlds retain their mode and are labelled. Physical feet include ankle/toe links.",
 "muscles":"control.muscles:{joint_name:effort -1..1}; equal/opposite internal torque, capped by strength. control.servos:{joint_name:{angle:relative radians,stiffness?:0..30000,damping?:0..3000,max_torque?:positive}} supplies an explicit relative PD muscle servo; no world-aligned posture. Use s.articulation[name]{angle,velocity,min,max,max_torque,torque}; shoulders=left/right_elbow, elbows=left/right_hand, hips=left/right_knee,knees=left/right_foot,ankles=left/right_toe,neck=head; appendage IDs are joints too. Learn balance/walking from physical feedback, never claim a predefined drive is learned walking.",
 "body":"body {body:{id,shape:'circle'|'rect'|'polygon',x,y,motion?:'dynamic'|'static',material?:name,mass?:.02..100,depth?:.005..1,friction?:0..2,restitution?:0..1,color?,angle?,radius OR width,height OR vertices:[[x,y],...]}}. Position is center, vertices local convex polygon. Material density computes mass from area/(100px per meter)^2*depth unless mass is explicit. Materials are illustrative configurable coefficients. Max64 objects.",
 "substance":"substance {name,values:{density:10..30000,friction:0..2,restitution:0..1,color:'#RRGGBB'}}. Define arbitrary named materials; edits update existing bodies referring to that material, preserving explicit overrides.",
 "joint":"joint {joint:{id,type:'pivot'|'pin'|'slide'|'spring'|'motor'|'gear'|'rotary_limit'|'rotary_spring'|'weld',a,b,anchor_a?:[x,y],anchor_b?:[x,y],anchor?:[world_x,world_y],length?,min?,max?,rate?,ratio?,phase?,stiffness?,damping?,max_force?,break_force?,collide?}}. Endpoints are body IDs, 'world', 'self:right_hand' or any skeleton/appendage joint name. Local anchors offset that endpoint; world anchors are world coordinates. Legacy pivot anchor is one shared world point. Slide is a distance limiter; gear couples rotations; weld fixes relative rotation. Motor max_force is torque, not linear force. Max96 joints.",
 "rope":"rope {rope:{id,a,b,anchor_a?:[x,y],anchor_b?:[x,y],points:[[world_x,world_y],...],segment_length?:8..30,radius?:1..4,mass_per_meter?:.01..3,break_force?:100..200000,color?:'#RRGGBB'}}. The chain uses real massive capsule links/pivots and collides with wheels, ground and bodies. Route endpoints are snapped to the specified current attachment points when a new chain is constructed. Route points around a pulley rim; there is no rope-through-wheel shortcut. Tension-only slack comes from the flexible chain. Max6 ropes /192 links total. remove_rope{id}. A routed chain is a 2D discretization, not an exact continuum rope solver.",
 "actuators":"control.joint_controls:{mechanism_id:{rate?:-30..30,max_force?:0..declared_cap}} controls motors; missing motors keep authored settings. Physical mode rejects drive, jump, pose, free body/object forces and absolute appendage_pose. Use real joints, muscles and contacts. s.mechanisms exposes constraint force/torque, broken flags, endpoints; s.ropes exposes peak tension and length; s.energy exposes positive muscle/motor work in simulation units. Static world anchors are explicit and visible.",
 "environment":"environment {values:{sky_top,sky_bottom,ground_top,ground_bottom:'#RRGGBB',sun:{x,y,radius,color},clouds:[{x,y,scale}],mountains:[{points:[[x,y],...],color}]}}. Whole appearance is editable; project draw can layer custom world/screen graphics or replace body drawing. Terrain is constructed with static physical polygons, not painted hills. Floor remains y540. No mandatory props or stories.",
 "skills":"widget {widget:{kind:'skill',id,title,icon?:'muscle'|'rope'|'wheel'|'hand'|'spark'|emoji_or_text,hotkey?:'1'..'9',x,y,width,height,target:{type:'project',name,event}}}. Skill icons appear in a persistent game hotbar and dispatch local project events without LLM calls. A labelled button is an authored ability binding, not evidence of mastered locomotion.",
 "evidence":"game_iteration verify:[{label,expression}] evaluates boolean expressions over candidate trial r. r.objects[id] has dx,dy,end_x,end_y,min_x,max_x,min_y,max_y,rotation; r.ropes[id] has broken,length,peak_tension; r.muscle_work/r.motor_work and upright_ratio are also available. Failed author predicates keep the live world unchanged; predicates are author-selected, not independent certification. Trials report finite physics, upright/grounded fraction, displacement, work and assistance mode. Falling is a legitimate learning result, not automatically a rejected edit. Test passing never means walking is learned or a mechanism's intended task is solved. Human dragging is an explicitly external force; it is separate from autonomous muscle work.",
}


def color(value):
    if not isinstance(value,str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",value):raise ValueError("color must be #RRGGBB")
    return value


def initialize_physical(world):
    world["body_control"]["mode"]="physical"
    world["body_control"]["self_collision"]=True
    world["environment"]=copy.deepcopy(ENVIRONMENT)
    add_feet(world)
    from .character import initialize
    initialize(world)


def add_feet(world):
    for side in ("left","right"):
        foot=world["nodes"][side+"_foot"]
        world["nodes"].setdefault(side+"_toe",{k:foot[k]+(13 if k in ("x","px") else 0) for k in foot})


def endpoint_names(world):
    nodes=set(world["nodes"])|{p["id"] for p in world["appendages"]}
    return {"world"}|{o["id"] for o in world["objects"] if o["kind"]=="body"}|nodes|{"self:"+n for n in nodes}


def point(value,name,limit=2000):
    from .world import number
    if not isinstance(value,list) or len(value)!=2:raise ValueError(name+" must be [x,y]")
    for v in value:number(v,-limit,limit,name)
    return value


def body(world,args):
    from .world import keys, number, text
    keys(args,("operation","body"));obj=copy.deepcopy(args.get("body"))
    allowed=("id","shape","x","y","width","height","radius","vertices","mass","depth","material","friction","restitution","color","label","angle","motion")
    keys(obj,allowed);text(obj.get("id"),40,"body id")
    if obj["id"] in endpoint_names(world)-{o["id"] for o in world["objects"]}:raise ValueError("body id conflicts with an endpoint")
    if obj.get("shape") not in ("rect","circle","polygon"):raise ValueError("body shape must be rect, circle or polygon")
    for k in ("x","y"):number(obj.get(k),-500,1500,k)
    if obj.get("motion","dynamic") not in ("dynamic","static"):raise ValueError("motion is dynamic or static")
    if "angle" in obj:number(obj["angle"],-20,20,"angle")
    if obj["shape"]=="circle":
        number(obj.get("radius"),3,200,"radius");area=math.pi*obj["radius"]**2
    elif obj["shape"]=="rect":
        for k in ("width","height"):number(obj.get(k),4,1000,k)
        area=obj["width"]*obj["height"]
    else:
        vertices=obj.get("vertices")
        if not isinstance(vertices,list) or not 3<=len(vertices)<=16:raise ValueError("convex polygon needs3..16 vertices")
        for p in vertices:point(p,"vertex",500)
        signs=[]
        for a,b,c in zip(vertices,vertices[1:]+vertices[:1],vertices[2:]+vertices[:2]):
            cross=(b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
            if abs(cross)>.0001:signs.append(cross>0)
        if not signs or len(set(signs))!=1:raise ValueError("polygon must be ordered and convex")
        area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(vertices,vertices[1:]+vertices[:1])))/2
        if area<4:raise ValueError("polygon area too small")
        for a,b in zip(vertices,vertices[1:]+vertices[:1]):
            sides={(b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])>0 for p in vertices if abs((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))>.001}
            if len(sides)>1:raise ValueError("polygon boundary must be convex and nonintersecting")
    material=obj.get("material")
    if material is not None and material not in world["substances"]:raise ValueError("unknown material")
    substance=world["substances"].get(material,{})
    number(obj.get("depth",.05),.005,1,"depth")
    # Preserve authored fields separately from computed coefficients.
    definition=copy.deepcopy(obj)
    obj.setdefault("mass",min(100,max(.02,substance["density"]*area/10000*obj.get("depth",.05))) if substance else 2)
    number(obj["mass"],.02,100,"mass")
    for k,default,hi in (("friction",.85,2),("restitution",.2,1)):
        obj.setdefault(k,substance.get(k,default));number(obj[k],0,hi,k)
    obj.setdefault("color",substance.get("color","#b7c5a4"));color(obj["color"])
    if "label" in obj:text(obj["label"],80,"label")
    obj.update(kind="body",definition=definition,vx=0,vy=0)
    index=next((i for i,o in enumerate(world["objects"]) if o["id"]==obj["id"]),None)
    if index is None:
        if len(world["objects"])>=64:raise ValueError("object limit64")
        world["objects"].append(obj)
    else:world["objects"][index]=obj
    return {"kind":"design","operation":"body"}


def joint(world,args):
    from .world import keys,number,text
    keys(args,("operation","joint"));j=copy.deepcopy(args.get("joint"))
    keys(j,("id","type","a","b","anchor","anchor_a","anchor_b","length","stiffness","damping","rate","max_force","min","max","ratio","phase","break_force","collide"))
    text(j.get("id"),40,"joint id")
    if j.get("type") not in ("pivot","pin","slide","spring","motor","gear","rotary_limit","rotary_spring","weld"):raise ValueError("unknown constraint type")
    ids=endpoint_names(world)
    if j.get("a") not in ids or j.get("b") not in ids or j["a"]==j["b"]:raise ValueError("joint needs two distinct valid endpoints")
    for k in ("anchor","anchor_a","anchor_b"):
        if k in j:point(j[k],k)
    for k,d,lo,hi in (("length",50,0,2000),("stiffness",50,0,100000),("damping",8,0,10000),("rate",0,-30,30),("max_force",20000,0,200000),("min",0,-20,2000),("max",100,-20,2000),("ratio",1,-20,20),("phase",0,-20,20),("break_force",200000,1,200000)):
        j.setdefault(k,d);number(j[k],lo,hi,k)
    if j["type"] in ("slide","rotary_limit") and j["min"]>j["max"]:raise ValueError("min must not exceed max")
    if j["type"]=="slide" and j["min"]<0:raise ValueError("slide min must be nonnegative")
    if j["type"]=="gear" and abs(j["ratio"])<.01:raise ValueError("gear ratio cannot be zero")
    j.setdefault("collide",False)
    if type(j["collide"]) is not bool:raise ValueError("collide must be boolean")
    index=next((i for i,old in enumerate(world["mechanisms"]) if old["id"]==j["id"]),None)
    if index is None:
        if len(world["mechanisms"])>=96:raise ValueError("joint limit96")
        world["mechanisms"].append(j)
    else:world["mechanisms"][index]=j
    return {"kind":"design","operation":"joint"}


def edit(world,args):
    from .world import keys,number,text
    operation=args.get("operation")
    if operation=="body_control":
        keys(args,("operation","values"));values=args.get("values");keys(values,BODY_CONTROL)
        if "mode" in values and values["mode"] not in ("physical","assisted"):raise ValueError("mode is physical or assisted")
        for k,lo,hi in (("muscle_scale",.1,3),("air_damping",.95,1),("joint_damping",0,100)):
            if k in values:number(values[k],lo,hi,k)
        if "self_collision" in values and type(values["self_collision"]) is not bool:raise ValueError("self_collision is boolean")
        world["body_control"].update(values)
        if world["body_control"]["mode"]=="physical":add_feet(world)
    elif operation=="substance":
        keys(args,("operation","name","values"));name=text(args.get("name"),40,"material name");v=copy.deepcopy(world["substances"].get(name,{}));keys(args.get("values"),("density","friction","restitution","color"));v.update(args["values"])
        for k,lo,hi in (("density",10,30000),("friction",0,2),("restitution",0,1)):number(v.get(k),lo,hi,k)
        color(v.get("color"))
        if name not in world["substances"] and len(world["substances"])>=20:raise ValueError("material limit20")
        world["substances"][name]=v
        for o in list(world["objects"]):
            if o.get("material")==name:
                current=copy.deepcopy(o);body(world,{"operation":"body","body":o["definition"]})
                updated=next(p for p in world["objects"] if p["id"]==o["id"])
                for k in ("x","y","vx","vy","angle","angular_velocity"):
                    if k in current:updated[k]=current[k]
    elif operation=="rope":
        keys(args,("operation","rope"));rope=copy.deepcopy(args.get("rope"));keys(rope,("id","a","b","anchor_a","anchor_b","points","segment_length","radius","mass_per_meter","break_force","color"));text(rope.get("id"),40,"rope id")
        if rope.get("a") not in endpoint_names(world) or rope.get("b") not in endpoint_names(world):raise ValueError("unknown rope endpoint")
        if rope["a"]==rope["b"]:raise ValueError("rope endpoints must differ")
        for k in ("anchor_a","anchor_b"):
            if k in rope:point(rope[k],k)
        pts=rope.get("points")
        if not isinstance(pts,list) or not 2<=len(pts)<=32:raise ValueError("rope needs2..32 route points")
        for p in pts:point(p,"route point")
        for k,d,lo,hi in (("segment_length",14,8,30),("radius",1.8,1,4),("mass_per_meter",.08,.01,3),("break_force",50000,100,200000)):
            rope.setdefault(k,d);number(rope[k],lo,hi,k)
        rope.setdefault("color","#d8b777");color(rope["color"])
        pieces=sum(max(1,math.ceil(math.dist(a,b)/rope["segment_length"])) for a,b in zip(pts,pts[1:]))
        if pieces>96:raise ValueError("rope link limit96")
        rope["link_count"]=pieces
        rest=[r for r in world["ropes"] if r["id"]!=rope["id"]]
        if len(rest)>=6 or pieces+sum(r["link_count"] for r in rest)>192:raise ValueError("rope budget6 ropes /192 links")
        world["ropes"]=rest+[rope]
        world["rope_state"].pop(rope["id"],None)
    elif operation=="remove_rope":
        keys(args,("operation","id"))
        if not any(r["id"]==args.get("id") for r in world["ropes"]):raise ValueError("rope not found")
        world["ropes"]=[r for r in world["ropes"] if r["id"]!=args["id"]];world["rope_state"].pop(args["id"],None)
    elif operation=="environment":
        keys(args,("operation","values"));v=copy.deepcopy(world.get("environment") or ENVIRONMENT);values=args.get("values");keys(values,ENVIRONMENT);v.update(copy.deepcopy(values))
        for k in ("sky_top","sky_bottom","ground_top","ground_bottom"):color(v[k])
        sun=v["sun"];keys(sun,("x","y","radius","color"));number(sun.get("x"),-1000,2000,"sun x");number(sun.get("y"),-1000,2000,"sun y");number(sun.get("radius"),0,200,"sun radius");color(sun.get("color"))
        if not isinstance(v["clouds"],list) or len(v["clouds"])>24:raise ValueError("cloud limit24")
        for c in v["clouds"]:
            keys(c,("x","y","scale"));number(c.get("x"),-1000,2000,"cloud x");number(c.get("y"),-500,1000,"cloud y");number(c.get("scale",1),.1,4,"cloud scale")
        if not isinstance(v["mountains"],list) or len(v["mountains"])>12:raise ValueError("mountain limit12")
        for m in v["mountains"]:
            keys(m,("points","color"));color(m.get("color"))
            if not isinstance(m.get("points"),list) or not 3<=len(m["points"])<=24:raise ValueError("mountain polygon needs3..24 points")
            for p in m["points"]:point(p,"mountain point")
        world["environment"]=v
    return {"kind":"design","operation":operation}
