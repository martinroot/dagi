"""Agent-owned multi-file JavaScript projects executed beside server physics.

QuickJS has no Python callbacks, filesystem, network or browser APIs. Programs
return bounded data: physical controls, camera, expression and vector graphics.
The source is general JavaScript, not a catalogue of activities or story beats.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading

import quickjs

_CACHE = threading.local()

HELP = {
    "edit": "project {name,description,files:{'main.js':source,...},entry?:'main.js',activate?:true}; edits one named project; files merge with existing files unless replace:true; <=12 files, <=48000 source chars total. Each file is CommonJS: module.exports; require('./helper.js') loads project files only. Main exports a synchronous function(input). Full JS functions, loops, classes, math and arrays work.",
    "input": "{t,dt,s,state,params,event}; t is seconds since this project was activated, dt=1/60; s is current physical sensors incl joints, objects, appendages, contact_evidence:{objects,support,joints,grip}, runtime{thinking,status}; state is your durable JSON state; event is a queued human project event or null; params is your saved numeric parameters.",
    "physical_control":"For an unassisted body use control.muscles and relative servos; drive/jump/pose/free forces are unavailable. s.articulation,s.mechanisms,s.ropes,s.energy provide physical evidence. Read game_observe view=schema,path=physics for exact construction/control.",
    "return": "{control?,state?,camera?,expression?,draw?,caption?,beat?,hide_body?}; all omitted channels reset to neutral each tick except state. control uses existing drive/jump/pose/forces/object_forces/grip, plus appendage_pose:{id:absolute_angle_radians}. Physical output is validated and applied to real motors.",
    "camera": "{target:'head'|'hip'|joint_name|object_id|appendage_id|[world_x,world_y],zoom:.65..4,offset:[x,y],ease:.05..3,shake:0..5,letterbox:0...18}; target tracks live physics. Default overview center [500,300], zoom1. Framing is presentation, never a physical teleport.",
    "expression": "{valence:-1..1,arousal:0..1,focus:0..1,surprise:0..1,mouth:0..1,squint:0..1,tilt:-.5...5,gaze:[x,y]}; cues are authored expression, not claims of felt emotion.",
    "draw": "<=120 vector commands, each {type:line|circle|ellipse|rect|text|path,x,y,...,fill?:#RRGGBB,stroke?:#RRGGBB,width?:line_width,alpha?:0..1,space?:world|screen,layer?:background|foreground}. line:x2,y2; circle:radius; ellipse:rx,ry,angle?; rect:w,h,radius?; text:text,size?; path:points[[x,y],...],closed?. World commands share the camera; screen commands stay fixed. hide_body:true lets you draw a complete custom visual body using real joint positions.",
    "anatomy": "appendage {part:{id,parent:existing_joint_or_previously_defined_appendage_id,length:8..90,angle:-6.3..6.3,radius:2..10,mass:.05..3,color:#RRGGBB}}; adds/updates a real capsule limb with pivot and rotary motor. appendage_pose sets its angle. remove_appendage{id} removes its descendant chain. Body appendages participate in collisions. Physical mode uses internal muscles and joint limits; assisted mode retains its explicitly labelled posture aids.",
    "human_controls": "widget or component event target:{type:'project',name:project_name,event?:your_event_id} runs locally without API. Your program receives input.event once; generic viewer button sends human_attention. Use event-driven reactions, not only timed choreography.",
    "world_edits": "body{body},joint{joint},remove_body{id},remove_joint{id},controller{values},physics{values},appearance{values},theme{values},component{component},widget{widget},project{...},appendage{part} can be submitted together in one game_iteration. Up to24 changes. No built-in scene sequence.",
    "limits": "8 MB JS heap, 256 KB stack, 8 ms CPU per invocation; no async, host imports, network or filesystem; state <=8 KB, output <=32 KB. Project runs at60Hz on server without API calls or open browser. Use state for memory; global variables are not durable and must not hold behavior state. Installed engine/auth/billing code is not hot-patched by project files.",
    "evaluation": "A full 12-second physical rollout exercises a project before release. Finite execution and physical checks do not establish aesthetic or task success. Inspect actual browser observations and human feedback; game_observe view=code returns small projects or a file index; path selects one file, offset pages it in5000-character chunks. A failed live project is disabled and preserves its source/error.",
    "example_syntax_only": "module.exports = ({t,s,state}) => { const target=state.target??500; return {state:{target},control:{drive:Math.max(-1,Math.min(1,(target-s.x)/90))},camera:{target:'hip',zoom:1.3},expression:{focus:.8,gaze:[target,s.y-60]},beat:'approach',caption:'Проверяю движение'}; };",
}


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _compiled(project, scope="compile"):
    """One runtime per project AND thread. Never pass contexts across threads."""
    cache = getattr(_CACHE, "items", None)
    if cache is None:
        cache = _CACHE.items = {}
    key = (scope, project["version"])
    if key not in cache:
        ctx = quickjs.Context()
        ctx.set_memory_limit(8 * 1024 * 1024)
        ctx.set_max_stack_size(256 * 1024)
        ctx.set_time_limit(.008)
        # Capture serializer/loader in a closure, outside the authored function.
        source = """(()=>{const parse=JSON.parse.bind(JSON), stringify=JSON.stringify.bind(JSON);
const files=FILES;
const factories=Object.create(null);
for(const [name,code] of Object.entries(files))factories[name]=new Function('module','exports','require',code);
return (encoded)=>{const cache=Object.create(null);
function load(name){
 if(!Object.prototype.hasOwnProperty.call(files,name))throw Error('Unknown project file: '+name);
 if(cache[name])return cache[name].exports;
 const module={exports:{}};cache[name]=module;
 const directory=name.includes('/')?name.slice(0,name.lastIndexOf('/')+1):'';
 const require=(path)=>{let p=path.startsWith('./')?directory+path.slice(2):path;return load(p);};
 factories[name](module,module.exports,require);return module.exports;
}
const main=load(ENTRY);if(typeof main!=='function')throw Error('Entry must export a function(input)');
const result=main(parse(encoded));
 if(!result||typeof result!=='object'||Array.isArray(result)||typeof result.then==='function')throw Error('Return a synchronous output object');
 const out=stringify(result);if(out.length>32768)throw Error('Project output exceeds32KB');return out;};})()"""
        source = source.replace("ENTRY", _encode(project["entry"])).replace("FILES", _encode(project["files"]))
        try:
            main = ctx.eval(source)
        except quickjs.JSException as exc:
            raise ValueError("project compile: " + str(exc)[:240]) from exc
        if len(cache) >= 24:
            cache.pop(next(iter(cache)))
        cache[key] = (ctx, main)
    return cache[key]


def define(world, args):
    from .world import keys, number, text
    from .studio import digest
    keys(args, ("operation", "name", "description", "files", "entry", "activate", "params", "replace"))
    name = text(args.get("name"), 40, "project name")
    if name in world["policies"]:raise ValueError("use a project name distinct from saved policy names")
    if type(args.get("replace",False)) is not bool:raise ValueError("replace must be boolean")
    existing=world["projects"].get(name,{})
    supplied=args.get("files")
    if not isinstance(supplied,dict):raise ValueError("files must be a JavaScript source dictionary")
    files={} if args.get("replace",False) else copy.deepcopy(existing.get("files",{}))
    files.update(supplied)
    if not isinstance(files, dict) or not 1 <= len(files) <= 12:
        raise ValueError("project files must contain1..12 JavaScript source files")
    if any(not isinstance(k,str) or not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*\.js", k) for k in files):
        raise ValueError("project filenames use relative letters/numbers/dashes and .js; no .. paths")
    for source in files.values():
        text(source, 24000, "JavaScript source")
    if sum(map(len,files.values())) > 48000:
        raise ValueError("project total source limit:48000 characters")
    entry = args.get("entry", existing.get("entry","main.js"))
    if entry not in files:
        raise ValueError("project entry must name an included file")
    if type(args.get("activate",True)) is not bool:
        raise ValueError("activate must be boolean")
    params = args.get("params",existing.get("params",{}))
    if not isinstance(params,dict) or len(params)>24:
        raise ValueError("project params is a small numeric dictionary")
    for key,value in params.items():
        text(key,40,"parameter name");number(value,-2000,2000,"parameter")
    project = {"files":copy.deepcopy(files), "entry":entry, "description":text(args.get("description"),240,"project description"), "params":params}
    project["version"] = digest(project)[:16]
    _compiled(project)
    if name not in world["projects"] and len(world["projects"])>=12:
        raise ValueError("at most12 saved projects")
    world["projects"][name] = project
    if args.get("activate",True):
        world.update(active_project=name, active_policy=None, project_state={}, project_started=world["tick"], project_error=None)
        world["event_queue"] = []
    return {"kind":"design", "operation":"project", "name":name}


def validate_draw(commands):
    from .world import number, text
    if not isinstance(commands,list) or len(commands)>120:
        raise ValueError("draw supports up to120 commands")
    for c in commands:
        if not isinstance(c,dict) or c.get("type") not in ("line","circle","ellipse","rect","text","path"):
            raise ValueError("unknown project drawing primitive")
        if c.get("space","world") not in ("world","screen") or c.get("layer","foreground") not in ("foreground","background"):
            raise ValueError("drawing space/layer is invalid")
        for key in ("fill","stroke"):
            if key in c and (not isinstance(c[key],str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",c[key])):
                raise ValueError("draw colors use#RRGGBB")
        number(c.get("alpha",1),0,1,"draw alpha")
        number(c.get("width",2),.1,30,"draw line width")
        for k in ("x","y"):
            number(c.get(k,0) if c["type"]=="path" else c.get(k),-2000,3000,k)
        if c["type"]=="path":
            points=c.get("points")
            if not isinstance(points,list) or not 2<=len(points)<=64:
                raise ValueError("path requires2..64 points")
            if type(c.get("closed",False)) is not bool:raise ValueError("path closed must be boolean")
            for p in points:
                if not isinstance(p,list) or len(p)!=2:raise ValueError("path points use[x,y]")
                for v in p:number(v,-2000,3000,"path point")
        if c["type"]=="line":
            for k in ("x2","y2"):number(c.get(k),-2000,3000,k)
        for k in {"circle":("radius",),"ellipse":("rx","ry"),"rect":("w","h")}.get(c["type"],()):
            number(c.get(k),0,2000,k)
        if "angle" in c:number(c["angle"],-100,100,"draw angle")
        if "radius" in c:number(c["radius"],0,2000,"draw radius")
        if c["type"]=="text":
            text(c.get("text"),240,"draw text");number(c.get("size",16),6,80,"text size")
    return commands


def command(world):
    from .living import sensors, validate_control
    from .world import number
    name=world["active_project"]
    project=world["projects"][name]
    ctx, main = _compiled(project, world.get("project_scope") or world["body_id"])
    sensor=sensors(world)
    sensor.update(appendages=copy.deepcopy(world["appendage_frames"]), runtime={k:world["life"].get(k) for k in ("thinking","status")})
    data={"t":(world["tick"]-world["project_started"])/60,"dt":1/60,"s":sensor,
          "state":world["project_state"],"params":project.get("params",{}),"event":world["event_queue"][0] if world["event_queue"] else None}
    try:
        output=json.loads(main(_encode(data)))
    except (quickjs.JSException,TypeError,json.JSONDecodeError) as exc:
        # Discard a potentially corrupted runtime after any execution failure.
        getattr(_CACHE,"items",{}).pop((world.get("project_scope") or world["body_id"],project["version"]),None)
        raise ValueError("project runtime: "+str(exc)[:240]) from exc
    if not isinstance(output,dict) or set(output)-{"control","state","camera","expression","draw","caption","beat","hide_body"}:
        raise ValueError("project returns control,state,camera,expression,draw,caption,beat,hide_body")
    state=output.get("state",world["project_state"])
    if not isinstance(state,dict) or len(_encode(state))>8192:
        raise ValueError("project state must be a JSON object <=8KB")
    camera=output.get("camera",{})
    if not isinstance(camera,dict) or set(camera)-{"target","zoom","offset","ease","shake","letterbox"}:
        raise ValueError("invalid project camera")
    target=camera.get("target",[500,300])
    if isinstance(target,str):
        targets=set(world["nodes"])|{o["id"] for o in world["objects"]}|{p["id"] for p in world["appendages"]}
        if target not in targets:raise ValueError("unknown camera target: "+target)
    else:
        if not isinstance(target,list) or len(target)!=2:raise ValueError("camera target is joint/object id or[x,y]")
        for v in target:number(v,-1000,2000,"camera target")
    offset=camera.get("offset",[0,0])
    if not isinstance(offset,list) or len(offset)!=2:raise ValueError("camera offset is[x,y]")
    for v in offset:number(v,-500,500,"camera offset")
    for key,default,lo,hi in (("zoom",1,.65,4),("ease",.35,.05,3),("shake",0,0,5),("letterbox",0,0,.18)):
        number(camera.get(key,default),lo,hi,key)
    for key,limit in (("caption",180),("beat",80)):
        if key in output and (not isinstance(output[key],str) or len(output[key])>limit):raise ValueError(key+" exceeds text limit")
    if type(output.get("hide_body",False)) is not bool:raise ValueError("hide_body must be boolean")
    draw=validate_draw(output.get("draw",[]))
    control=copy.deepcopy(output.get("control",{}))
    if not isinstance(control,dict):raise ValueError("control must be object")
    control["emotion"]=output.get("expression",{})
    if isinstance(control["emotion"],dict) and "gaze" in control["emotion"]:
        control["gaze"]=control["emotion"].pop("gaze")
    # Always reset authored face channels so omitted surprise cannot stick forever.
    control["emotion"]={"valence":0,"arousal":.25,"focus":.4,"surprise":0,"mouth":0,"squint":0,"tilt":0,**control["emotion"]} if isinstance(control["emotion"],dict) else control["emotion"]
    if "gaze" not in control:world["emotion"].pop("gaze",None)
    validate_control(world,control)
    world["project_state"]=copy.deepcopy(state)
    if world["event_queue"]:world["event_queue"].pop(0)
    world["direction"]={"camera":camera,"draw":draw,"caption":output.get("caption",""),"beat":output.get("beat",""),"hide_body":output.get("hide_body",False)}
    world["life"]["intent"]=output.get("caption") or output.get("beat", "")
    return control


def anatomy(world, args):
    from .world import keys, number, text
    operation=args.get("operation")
    if operation=="appendage":
        keys(args,("operation","part"))
        part=copy.deepcopy(args.get("part"))
        keys(part,("id","parent","length","angle","radius","mass","color"))
        text(part.get("id"),40,"part id")
        if part["id"] in world["nodes"] or part["id"] in {o["id"] for o in world["objects"]}:raise ValueError("part id must be distinct from skeleton joints and objects")
        existing=next((i for i,p in enumerate(world["appendages"]) if p["id"]==part["id"]),None)
        # Ordered tree ensures no cycles and deterministic physics construction.
        earlier=world["appendages"][:existing] if existing is not None else world["appendages"]
        if part.get("parent") not in set(world["nodes"])|{p["id"] for p in earlier}:
            raise ValueError("parent must be skeleton joint or earlier appendage")
        for k,d,lo,hi in (("length",40,8,90),("angle",0,-6.3,6.3),("radius",4,2,10),("mass",.25,.05,3)):
            part.setdefault(k,d);number(part[k],lo,hi,k)
        part.setdefault("color",world["appearance"]["accent"])
        if not isinstance(part["color"],str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",part["color"]):raise ValueError("part color uses#RRGGBB")
        if existing is None:
            if len(world["appendages"])>=12:raise ValueError("at most12 physical appendages")
            world["appendages"].append(part)
        else:world["appendages"][existing]=part
    elif operation=="remove_appendage":
        keys(args,("operation","id"))
        if args.get("id") not in {p["id"] for p in world["appendages"]}:raise ValueError("appendage not found")
        removed={args["id"]}
        for part in world["appendages"]:
            if part["parent"] in removed:removed.add(part["id"])
        endpoints=removed|{"self:"+n for n in removed}
        world["mechanisms"]=[j for j in world["mechanisms"] if j["a"] not in endpoints and j["b"] not in endpoints]
        world["ropes"]=[r for r in world["ropes"] if r["a"] not in endpoints and r["b"] not in endpoints]
        world["appendages"]=[p for p in world["appendages"] if p["id"] not in removed]
        world["appendage_frames"]=[p for p in world["appendage_frames"] if p[0] not in removed]
    elif operation=="remove_body":
        keys(args,("operation","id"))
        if not any(o["kind"]=="body" and o["id"]==args.get("id") for o in world["objects"]):raise ValueError("physical body not found")
        world["objects"]=[o for o in world["objects"] if o["id"]!=args["id"]]
        world["ropes"]=[r for r in world["ropes"] if args["id"] not in (r["a"],r["b"])]
        world["mechanisms"]=[j for j in world["mechanisms"] if args["id"] not in (j["a"],j["b"])]
    elif operation=="remove_joint":
        keys(args,("operation","id"))
        if not any(j["id"]==args.get("id") for j in world["mechanisms"]):raise ValueError("mechanism joint not found")
        world["mechanisms"]=[j for j in world["mechanisms"] if j["id"]!=args["id"]]
    return {"kind":"design","operation":operation}
