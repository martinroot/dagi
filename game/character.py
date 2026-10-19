"""Editable anatomical proportions shared by collision geometry and rendering.

No locomotion, balance or posture controller is installed by a character edit.
Torso attachment markers are rigid points, not additional hidden actuators.
"""
from __future__ import annotations
import copy
import math

BONES = {
    "hip": {"length":58,"radius":10,"mass":4},
    "left_elbow":{"length":31,"radius":5.5,"mass":.65},
    "right_elbow":{"length":31,"radius":5.5,"mass":.65},
    "left_hand":{"length":30,"radius":4.5,"mass":.5},
    "right_hand":{"length":30,"radius":4.5,"mass":.5},
    "left_knee":{"length":44,"radius":7,"mass":1.2},
    "right_knee":{"length":44,"radius":7,"mass":1.2},
    "left_foot":{"length":42,"radius":5,"mass":.8},
    "right_foot":{"length":42,"radius":5,"mass":.8},
    "left_toe":{"length":15,"radius":3.5,"mass":.22,"heel":0},
    "right_toe":{"length":15,"radius":3.5,"mass":.22,"heel":0},
}
FEATURES = {"hair":"none","hair_color":"#243b48","hair_length":.65,"iris":"#5baaa8","brow":"#31414b","lips":"#b67470","detail":.3,"freckles":0,"eye_size":1}
DEFAULT = {"name":"Origin", "style":"skeleton", "shoulder_width":27,"hip_width":17,"neck_length":18,"head_radius":11.5,"head_mass":1,
           "bones":BONES,"features":FEATURES,"surface":{"skin":"#b87c64","muscle":"#a6574b","bone":"#eee2cb","accent":"#527c7b","eye":"#263f42","roughness":.55,"metallic":.15,"outline":.65,"muscles":.75,"bone_visibility":0,"head_width":.85,"crest":0,"markings":.35,"fabric":"#344650","garment":0}}
ART = {"mode":"soft","ambient":.52,"key":{"x":180,"y":80,"color":"#fff1d0","intensity":.9},"shadow":.38,"rim":.55,"exposure":1,"vignette":.18,"grain":.06,"atmosphere":{"depth":.7,"haze":.3,"wind":.25,"vegetation":.5},"layers":[]}
HELP = {
 "character":"character {values:{name?,style?:'sticks'|'skeleton'|'anatomical'|'ceramic'|'ink',shoulder_width?:8..50,hip_width?:6..36,neck_length?:10..30,head_radius?:7..22,head_mass?:.2..5,bones?:{bone_name:{length?:8..100,radius?:2..18,mass?:.1..12,heel?:0..16 (toe only)}},surface?:{skin,muscle,bone,accent,eye:'#RRGGBB',roughness?:0..1,metallic?:0..1,outline?:0..2,muscles?:0..1,bone_visibility?:0..1,head_width?:.65..1,crest?:0..1,markings?:0..1,fabric?:'#RRGGBB',garment?:0..1}}}. Bone names: hip (torso), left/right_elbow (upper arm), left/right_hand (forearm), left/right_knee (thigh), left/right_foot (shin), left/right_toe. Features are cosmetic: hair none/crop/swept/spiky/bob, hair_color,iris,brow,lips colors; hair_length/detail/freckles0..1,eye_size.7..1.3. Partial nested edits merge. Radius is the real collision capsule radius, mass and length affect inertia. Surface muscle volume stays inside this envelope. Skull collision uses head_radius; head_width only sculpts the rendered face inside it. Skeleton style exposes ribs, spine, pelvis and paired bones; decorative ribs/fingers are not independent physical bodies. Additional physical limbs use appendage edits. No animation or ability is learned by changing style.",
 "morphology":"Shoulder and pelvis attachment points belong to the rigid torso. Bone edits reconstruct the tree preserving each current link direction and endpoint velocity; hip stays in place, body is raised only if the new envelope crosses the floor. No automatic standing. Existing mechanisms and ropes stay explicit. Changed dimensions require fresh physical trials. Publication remaps the latest live pose, not the earlier trial pose.",
 "art":"art {values:{mode?:'soft'|'toon'|'noir',ambient?:0..1,key?:{x:-1000..2000,y:-1000..2000,color:'#RRGGBB',intensity:0..2},shadow?:0..1,rim?:0..1,exposure?:.5..1.5,vignette?:0...6,grain?:0...2,atmosphere?:{depth?:0..1,haze?:0..1,wind?:0..1,vegetation?:0..1},layers?:[{id,depth?:-10..10,opacity?:0..1,parallax?:0..1,commands:[vector_command,...]}]}}. Up to12 vector layers,240 commands total,48KB art. All scenery is procedural vector geometry with shared lighting, no raster images. Environment edits control sky/ground/sun/clouds/mountains; atmosphere sets depth/haze/wind/grass. Layer parallax0 = distant backdrop,1 = ordinary world geometry; depth<0 renders behind the body,depth>=0 in front. Use JS project draw for authored dynamic shapes. Soft = smooth gradient volume, toon = stepped shading, noir = monochrome. Ground shadows are a 2D projection, not a 3D ray tracer.",
 "vectors":"Shared art layer / JS draw contract: line,circle,ellipse,rect,text,path and bezier. fill/stroke may be #RRGGBB or {type:'linear'|'radial',from:[x,y],to:[x,y],radius?:positive,stops:[[0..1,'#RRGGBB'],...]}; 2..8 ordered stops. bezier uses segments:[['M',x,y],['L',x,y],['Q',cx,cy,x,y],['C',c1x,c1y,c2x,c2y,x,y],['Z']], max64, starts M. Optional transform:[a,b,c,d,e,f] Canvas2D matrix, blend:'source-over'|'multiply'|'screen'|'overlay',shadow:{color:'#RRGGBB',blur:0..30,x:-40..40,y:-40..40},alpha:0..1; path uses points and closed; dimensions and coordinates follow project draw schema. Layers are editable scene structure, not physical colliders. Add static bodies for painted terrain that should support weight.",
 "state":"Read current character/art with game_observe view=visual; exact contract via view=schema,path=visual. The agent can author anatomy, geometry, vector composition, gradients, materials, lighting and camera. No external image generation, downloads or raster backgrounds are needed. Visual quality is human judgement; solver/contrast checks cannot certify it."
}


def physical_shape(character):
    return {k:v for k,v in (character or {}).items() if k not in ("name","style","surface","features")}


def bone_pairs(world):
    from .world import PAIRS
    if not world.get("character"):return PAIRS+[(s+"_foot",s+"_toe") for s in ("left","right") if s+"_toe" in world["nodes"]]
    return [("head","neck"),("neck","hip")]+[(s+"_"+a,s+"_"+b) for s in ("left","right") for a,b in (("shoulder","elbow"),("elbow","hand"),("pelvis","knee"),("knee","foot"),("foot","toe"))]


def bone_lengths(world):
    from .world import LINKS
    c=world.get("character")
    if not c:return LINKS
    return [(a,b,c["neck_length"] if a=="head" else c["bones"][b]["length"]) for a,b in bone_pairs(world)]


def anchors(character):
    # Local torso axis runs neck -> hip; perpendicular points to canvas left.
    return {s+"_shoulder":(-character["bones"]["hip"]["length"]/2+5,sign*character["shoulder_width"]/2) for s,sign in (("left",1),("right",-1))}|{s+"_pelvis":(character["bones"]["hip"]["length"]/2-3,sign*character["hip_width"]/2) for s,sign in (("left",1),("right",-1))}


def reshape(world, previous=None):
    """Rebuild authored lengths around the current hip without resetting pose."""
    c=world["character"]
    if not c:return
    old=copy.deepcopy(world["nodes"]); nodes=world["nodes"]
    hip=old["hip"]; origin=(hip["x"],hip["y"])
    def direction(a,b,fallback):
        if a not in old or b not in old:return fallback
        dx,dy=old[b]["x"]-old[a]["x"],old[b]["y"]-old[a]["y"];length=math.hypot(dx,dy)
        return (dx/length,dy/length) if length>.001 else fallback
    axis=direction("neck","hip",(0,1));length=c["bones"]["hip"]["length"]
    def place(name,x,y):
        p=old.get(name,old["hip"]);nodes[name]={"x":x,"y":y,"px":x-(p["x"]-p["px"]),"py":y-(p["y"]-p["py"])}
    place("neck",origin[0]-axis[0]*length,origin[1]-axis[1]*length)
    center=(origin[0]-axis[0]*length/2,origin[1]-axis[1]*length/2)
    for name,(along,across) in anchors(c).items():place(name,center[0]+axis[0]*along-axis[1]*across,center[1]+axis[1]*along+axis[0]*across)
    for a,b in bone_pairs(world):
        if b in ("neck","hip"):continue
        olda=a
        if a.endswith("shoulder") and a not in old:olda="neck"
        if a.endswith("pelvis") and a not in old:olda="hip"
        dx,dy=direction(olda,b,(.25,1));l=c["bones"][b]["length"]
        place(b,nodes[a]["x"]+dx*l,nodes[a]["y"]+dy*l)
    hx,hy=direction("neck","head",(0,-1));place("head",nodes["neck"]["x"]+hx*c["neck_length"],nodes["neck"]["y"]+hy*c["neck_length"])
    bottom=max(p["y"]+(c["head_radius"] if n=="head" else c["bones"].get(n,{"radius":0})["radius"]) for n,p in nodes.items())
    if bottom>538:
        for p in nodes.values():p["y"]-=bottom-538;p["py"]-=bottom-538
    world["articulation"]={};world["appendage_frames"]=[]


def initialize(world):
    world["character"] = copy.deepcopy(DEFAULT)
    world["art"] = copy.deepcopy(ART)
    key = ART["key"]
    world["environment"]["sun"] = {
        "x": key["x"], "y": key["y"], "radius": 26, "color": key["color"],
    }
    world["environment"]["clouds"] = [
        {"x":200,"y":115,"scale":.9},
        {"x":530,"y":76,"scale":1.2},
        {"x":830,"y":145,"scale":.65},
    ]
    reshape(world)


def edit(world,args):
    from .world import keys,number,text
    from .workshop import color
    keys(args,("operation","values"));v=args.get("values")
    if args["operation"]=="character":
        keys(v,DEFAULT);c=copy.deepcopy(world.get("character") or DEFAULT)
        geometry=any(k in v for k in ("bones","shoulder_width","hip_width","neck_length","head_radius","head_mass")) or not world.get("character")
        for k,lo,hi in (("shoulder_width",8,50),("hip_width",6,36),("neck_length",10,30),("head_radius",7,22),("head_mass",.2,5)):
            if k in v:number(v[k],lo,hi,k);c[k]=v[k]
        if "name" in v:c["name"]=text(v["name"],60,"character name")
        if "style" in v:
            if v["style"] not in ("skeleton","anatomical","ceramic","ink","sticks"):raise ValueError("unknown character style")
            c["style"]=v["style"]
        if "bones" in v:
            keys(v["bones"],BONES)
            for name,bone in v["bones"].items():
                keys(bone,("length","radius","mass","heel"))
                if "heel" in bone:
                    if not name.endswith("toe"):raise ValueError("heel is available on toe bodies only")
                    number(bone["heel"],0,16,"heel")
                for k,lo,hi in (("length",8,100),("radius",2,18),("mass",.1,12)):
                    if k in bone:number(bone[k],lo,hi,k)
                c["bones"][name].update(bone)
        if "features" in v:
            keys(v["features"],FEATURES);features={**FEATURES,**c.get("features",{})}
            for k,value in v["features"].items():
                if k=="hair":
                    if value not in ("none","crop","swept","spiky","bob"):raise ValueError("hair is none, crop, swept, spiky or bob")
                elif k in ("hair_color","iris","brow","lips"):color(value)
                else:number(value,*( (.7,1.3) if k=="eye_size" else (0,1)),k)
            features.update(v["features"]);c["features"]=features
        if "surface" in v:
            keys(v["surface"],DEFAULT["surface"])
            for k,value in v["surface"].items():
                if k in ("skin","muscle","bone","accent","eye","fabric"):color(value)
                else:number(value,*( (.65,1) if k=="head_width" else (0,2) if k=="outline" else (0,1)),k)
            c["surface"].update(v["surface"])
        if not world.get("character"):
            markers={"left_shoulder","right_shoulder","left_pelvis","right_pelvis","left_toe","right_toe"}
            occupied={o["id"] for o in world["objects"]}|{p["id"] for p in world["appendages"]}
            if markers&occupied:raise ValueError("anatomical marker id conflicts with an existing object/appendage")
        world["character"]=c
        world["physics_engine"]="chipmunk"
        if geometry:reshape(world)
    else:
        keys(v,ART);a=copy.deepcopy(world.get("art") or ART)
        for k in ("ambient","shadow","rim","exposure","vignette","grain"):
            if k in v:number(v[k],*( (.5,1.5) if k=="exposure" else (0,.6) if k=="vignette" else (0,.2) if k=="grain" else (0,1)),k)
        if "mode" in v and v["mode"] not in ("soft","toon","noir"):raise ValueError("art mode is soft, toon or noir")
        if "key" in v:
            keys(v["key"],ART["key"]);light={**a["key"],**v["key"]}
            for k,lo,hi in (("x",-1000,2000),("y",-1000,2000),("intensity",0,2)):number(light[k],lo,hi,k)
            color(light["color"]);v=copy.deepcopy(v);v["key"]=light
        if "atmosphere" in v:
            keys(v["atmosphere"],ART["atmosphere"])
            for k,value in v["atmosphere"].items():number(value,0,1,k)
            v=copy.deepcopy(v);v["atmosphere"]={**a["atmosphere"],**v["atmosphere"]}
        if "layers" in v:
            from .director import validate_draw
            if not isinstance(v["layers"],list) or len(v["layers"])>12:raise ValueError("vector layer limit12")
            ids=set();count=0
            for layer in v["layers"]:
                keys(layer,("id","depth","opacity","parallax","commands"))
                name=text(layer.get("id"),40,"layer id")
                if name in ids:raise ValueError("duplicate vector layer id")
                ids.add(name)
                for k,d,lo,hi in (("depth",-1,-10,10),("opacity",1,0,1),("parallax",1,0,1)):number(layer.get(k,d),lo,hi,k)
                validate_draw(layer.get("commands"));count+=len(layer["commands"])
            if count>240:raise ValueError("vector scene budget240 commands")
        import json
        if len(json.dumps({**a,**v}))>48000:raise ValueError("art exceeds48KB")
        a.update(copy.deepcopy(v));world["art"]=a
    return {"kind":"design","operation":args["operation"]}
