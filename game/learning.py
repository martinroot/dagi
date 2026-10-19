"""Versioned skill contracts, dense measured fitness and dependency-aware practice.

A successful tool invocation is never a skill certificate. Criteria, executable
source, physical configuration and prerequisite certificates bind every receipt.
"""
from __future__ import annotations
import copy
import math
import time
from uuid import uuid4

DEFAULT = {"goal":None,"target":None,"skills":{},"focus":None,"revision":0,"seed":{},"audit":[],"lessons":[]}
REDUCERS = {"min","max","mean","sum","last","integral","duration","longest","transitions"}
HELP = {
 "workflow":"game_train action=plan defines goal,target,skills and reason; action=evaluate tests an existing skill without publishing; action=note records hypothesis/next_change linked to an attempt. Read game_observe view=learning,path=skill_id for contract and attempts. Then game_iteration skill=id with project/policy/physical changes. The runtime compares baseline/candidate under the frozen contract; guard-safe improvement can publish without claiming mastery. Mastery requires every case success and current mastered prerequisites. No extra model calls during physics evaluation.",
 "plan":"{action:'plan',goal:human_goal,target:root_skill_id,reason:why_this_decomposition,skills:[{id,title,depends:[id,...],program:project_or_policy_name,metrics:[{name,expression,reduce,target?:{min?,max?}}],score:expression_over_r,success:boolean_expression_over_r,guards:[boolean_expression_over_r,...],cases:[case,...],min_delta?:0..100000,attempt_limit?:1..20,plateau_limit?:2..10}]}. Up to16 skills,12 metrics/skill,6 guards,5 cases/skill,6000 frames per assessment. All dependencies must exist and form a DAG. The final composed skill needs its own executable program and end-to-end contract: passed children alone do not prove composition. Program may be authored after planning. A changed contract invalidates its evidence and dependents; reason/audit persist.",
 "metric":"expression is a safe bounded Python expression over s (current sensors), prev (previous sensors), initial (start sensors); s has x,y,vx,vy,upright,grounded,joints,contacts,support,contact_evidence,articulation,energy,objects. Reducers min/max/mean/sum/last/integral require numeric values, duration/longest/transitions require bool. duration/longest are seconds; transitions counts false->true edges. Target min/max bounds are mandatory conditions when supplied. Every physics tick is sampled, not a browser frame or a sparse filmstrip. <=600 chars/expression. r adds metrics to standard trial report; score higher is better, must be numeric; success and guards must be boolean. All criteria are authored and visible, not independent certification.",
 "case":"{id,frames:30..1200,start:'neutral'|'captured',split:'train'|'validation',velocity?:[vx,vy],impulses?:[{at:0..1199,joint:node,value:[ix,iy]}],events?:[{at:0..1199,id:event_name}]}. Need at least one validation case. Neutral starts from an explicitly reset unassisted pose (not a learned recovery); captured uses plan's recorded pose, remapped to current proportions. Each case resets program state/time and object authored positions. Impulses are explicit external TEST disturbances. Up to8 impulses/events. Cases are declared regression/validation scenarios, not hidden independent holdouts. Do not rank a recovery skill tested only from a neutral standing start.",
 "anti_shortcuts":"r.external_supports includes the explicit powered stage rig when enabled, and counts constraints/ropes connecting the skeleton through bodies to static world anchors; r.powered_motors counts powered mechanism motors; r.mode exposes assistance; r.gravity is actual gravity. Use explicit guards when testing unsupported muscular locomotion. Example only: r['mode']=='physical' and r['external_supports']==0 and r['powered_motors']==0 and r['gravity']>=900. Meaningful walking criteria should combine sustained upright time, distance, real foot support changes and limited slip/airtime; displacement alone admits falling, crawling, sliding and external supports. No walking program or curriculum is installed.",
 "memory":"Contracts, bounded receipts, scores, worst failed cases and source hashes survive reload/restart. Only applied/current-source receipts can certify mastery; failed candidate receipts remain experiments. Human/agent notes are hypotheses tied to a receipt. No evaluator/source change can reuse a previous mastery certificate. Attempt/plateau limits stop unproductive autonomous paid turns. Pausing/restarting never silently resets budgets; an explicit new plan revision/retry budget is audited.",
}


def _expr(value,name):
    from .world import text
    from .living import parse
    text(value,600,name)
    try:
        parse(value)
    except ValueError as exc:
        raise ValueError(f"{name} expression: " + str(exc)[:180]) from exc
    return value


def plan(world,args):
    from .world import keys,text,number
    from .studio import digest
    keys(args,("action","goal","target","skills","reason"))
    text(args.get("goal"),400,"goal");text(args.get("reason"),400,"decomposition reason")
    supplied=args.get("skills")
    if not isinstance(supplied,list) or not 1<=len(supplied)<=16:raise ValueError("plan needs1..16 skill contracts")
    skills={}
    for raw in supplied:
        c=copy.deepcopy(raw);keys(c,("id","title","depends","program","metrics","score","success","guards","cases","min_delta","attempt_limit","plateau_limit"))
        id=text(c.get("id"),40,"skill id");text(c.get("title"),100,"skill title");text(c.get("program"),40,"program")
        if id in skills:raise ValueError("duplicate skill id")
        deps=c.setdefault("depends",[])
        if not isinstance(deps,list) or len(deps)>12 or any(not isinstance(d,str) for d in deps) or len(set(deps))!=len(deps):raise ValueError("depends is a list of unique skill ids")
        metrics=c.get("metrics")
        if not isinstance(metrics,list) or not 1<=len(metrics)<=12:raise ValueError("skill needs1..12 metrics")
        names=set()
        for m in metrics:
            keys(m,("name","expression","reduce","target","label","unit"));name=text(m.get("name"),40,"metric name")
            if name in names:raise ValueError("duplicate metric name")
            names.add(name);_expr(m.get("expression"),"metric expression")
            if "label" in m:text(m["label"],80,"metric label")
            if "unit" in m:text(m["unit"],16,"metric unit")
            if m.get("reduce") not in REDUCERS:raise ValueError("unknown metric reducer")
            if "target" in m:
                keys(m["target"],("min","max"))
                if not m["target"]:raise ValueError("metric target is empty")
                for v in m["target"].values():number(v,-1e8,1e8,"metric target")
                if m["target"].get("min",-1e8)>m["target"].get("max",1e8):raise ValueError("metric target min>max")
        _expr(c.get("score"),"fitness score");_expr(c.get("success"),"success predicate")
        guards=c.setdefault("guards",[])
        if not isinstance(guards,list) or len(guards)>6:raise ValueError("up to6 guards")
        for g in guards:_expr(g,"guard")
        cases=c.get("cases")
        if not isinstance(cases,list) or not 1<=len(cases)<=5:raise ValueError("skill needs1..5 cases")
        ids=set()
        for case in cases:
            keys(case,("id","frames","start","split","velocity","impulses","events"));name=text(case.get("id"),40,"case id")
            if name in ids:raise ValueError("duplicate case id")
            ids.add(name)
            if type(case.get("frames")) is not int or not 30<=case["frames"]<=1200:raise ValueError("case frames30..1200")
            if case.get("start") not in ("neutral","captured") or case.get("split") not in ("train","validation"):raise ValueError("case start/split must be explicit")
            if "velocity" in case:
                _vector(case["velocity"],500,"test velocity")
            for field in ("impulses","events"):
                values=case.get(field,[])
                if not isinstance(values,list) or len(values)>8:raise ValueError("up to8 disturbances/events")
                for value in values:
                    keys(value,("at","joint","value") if field=="impulses" else ("at","id"))
                    if type(value.get("at")) is not int or not 0<=value["at"]<case["frames"]:raise ValueError("disturbance at must be a case frame index")
                    if field=="impulses":
                        if value.get("joint") not in world["nodes"]:raise ValueError("unknown impulse joint")
                        _vector(value.get("value"),2000,"test impulse")
                    else:text(value.get("id"),60,"test event")
        if not any(x["split"]=="validation" for x in cases):raise ValueError("include at least one explicit validation case")
        for k,default,lo,hi in (("min_delta",.001,0,100000),("attempt_limit",12,1,20),("plateau_limit",5,2,10)):
            c.setdefault(k,default);number(c[k],lo,hi,k)
            if k!="min_delta" and type(c[k]) is not int:raise ValueError(k+" must be integer")
        c["version"]=digest(c)[:16];skills[id]=c
    target=args.get("target")
    if not isinstance(target,str) or target not in skills:raise ValueError("target skill must exist")
    visited=set()
    def visit(id,stack):
        if id in stack:raise ValueError("skill dependencies contain a cycle")
        if id not in skills:raise ValueError("unknown prerequisite: "+str(id))
        if id in visited:return
        for d in skills[id]["depends"]:visit(d,stack|{id})
        visited.add(id)
    for id in skills:visit(id,set())
    old=world["learning"]
    if world["life"].get("run_kind")=="autonomous" and any(c.get("attempts") for c in old["skills"].values()):
        if args["goal"]!=old["goal"] or target!=old["target"]:raise ValueError("the human goal/target is locked during autonomous practice")
        for id,previous in old["skills"].items():
            if not previous.get("attempts"):continue
            if id not in skills or any(skills[id][k]!=previous[k] for k in ("metrics","score","success","guards","cases")):
                raise ValueError("measured success criteria are locked during autonomous practice; refine code/decomposition or ask the human to revise the criteria explicitly")
    receipts={id:copy.deepcopy(old["skills"].get(id,{}).get("attempts",[])) for id in skills}
    for id,c in skills.items():
        c["attempts"]=receipts[id]
        if old["skills"].get(id,{}).get("working"):c["working"]=copy.deepcopy(old["skills"][id]["working"])
    seed=old["seed"] or {"nodes":copy.deepcopy(world["nodes"])}
    world["learning"]={**old,"goal":args["goal"],"target":target,"skills":skills,"seed":seed,"revision":old["revision"]+1,
                       "audit":(old["audit"]+[{"at":time.time(),"reason":args["reason"],"contracts":{k:c["version"] for k,c in skills.items()}}])[-12:]}
    world["learning"]["focus"]=next_focus(world)
    return {"kind":"learning_plan","learning":summary(world)}


def _vector(value,limit,name):
    from .world import number
    if not isinstance(value,list) or len(value)!=2:raise ValueError(name+" must be[x,y]")
    for v in value:number(v,-limit,limit,name)


def binding(world,id,cache=None):
    from .studio import configuration,digest
    from .character import physical_shape
    cache={} if cache is None else cache
    if id in cache:return cache[id]
    c=world["learning"]["skills"][id];name=c["program"]
    p=world["projects"].get(name) or world["policies"].get(name)
    config=configuration(world)
    physical={k:config[k] for k in ("physics_engine","gravity","controller","material","objects","mechanisms","appendages","body_control","substances","ropes","goal")}
    physical["character"]=physical_shape(world.get("character"))
    cache[id]=digest({"contract":c["version"],"program":p["version"] if p else None,"physics":physical,"seed":world["learning"]["seed"],"dependencies":{d:{"binding":binding(world,d,cache),"certificate":next((a["id"] for a in reversed(world["learning"]["skills"][d]["attempts"]) if a["binding"]==binding(world,d,cache) and a["applied"]),None)} for d in c["depends"]}})
    return cache[id]


def statuses(world):
    skills=world["learning"]["skills"];result={};bindings={}
    def check(id):
        if id in result:return result[id]
        c=skills[id];deps={d:check(d) for d in c["depends"]};sig=binding(world,id,bindings)
        attempts=[a for a in c["attempts"] if a["contract"]==c["version"]]
        valid=next((a for a in reversed(attempts) if a["binding"]==sig and a["applied"]),None)
        mastered=bool(valid and valid["passed"] and all(d["status"]=="mastered" for d in deps.values()))
        blocked=[d for d,v in deps.items() if v["status"]!="mastered"]
        recent=attempts[-c["plateau_limit"]:]
        plateau=len(recent)>=c["plateau_limit"] and not any(a["improved"] for a in recent)
        budget=len(attempts)>=c["attempt_limit"]
        status="mastered" if mastered else "blocked" if blocked or budget or plateau else "ready"
        result[id]={"id":id,"title":c["title"],"status":status,"depends":c["depends"],"attempts":len(attempts),"limit":c["attempt_limit"],"contract":c["version"],"score":valid["score"] if valid else None,
                    "reason":"prerequisites: "+", ".join(blocked) if blocked else "attempt budget exhausted" if budget and not mastered else "fitness plateau; change hypothesis or revise plan explicitly" if plateau and not mastered else None,
                    "last":({k:attempts[-1].get(k) for k in ("id","score","passed","improved","applied","bottleneck")} if attempts else None)}
        return result[id]
    for id in skills:check(id)
    return result


def next_focus(world):
    states=statuses(world);old=world["learning"]["focus"]
    # Only ancestors of the requested composed target consume autonomous work.
    needed=set()
    def add(id):
        if id in needed:return
        needed.add(id)
        for d in world["learning"]["skills"][id]["depends"]:add(d)
    if world["learning"]["target"]:add(world["learning"]["target"])
    if old in needed and states[old]["status"]=="ready":return old
    return next((id for id in states if id in needed and states[id]["status"]=="ready"),None)


def summary(world,details=False):
    l=world["learning"]
    if not l["goal"]:return {"goal":None,"status":"unplanned","focus":None,"skills":[]}
    states=statuses(world);complete=states[l["target"]]["status"]=="mastered";focus=next_focus(world)
    if details:
        for id,state in states.items():
            c=l["skills"][id]
            state["criteria"]=[{k:v for k,v in m.items() if k!="expression"} for m in c["metrics"]]
            state["success"]=c["success"]
            attempts=[a for a in c["attempts"] if a["contract"]==c["version"]]
            last=attempts[-1] if attempts else None
            if last and state["last"]:
                row=next((r for r in last["cases"] if not r["passed"]),last["cases"][0] if last["cases"] else {})
                state["last"]["metrics"]=row.get("metrics",[])
                state["last"]["error"]=row.get("error") or last.get("error")
                state["last"]["guard_failures"]=[g["expression"] for g in row.get("guards",[]) if not g["passed"]]
    return {"goal":l["goal"],"target":l["target"],"revision":l["revision"],"status":"mastered" if complete else "training" if focus else "blocked","focus":None if complete else focus,"skills":list(states.values()),"lessons":l["lessons"][-4:]}


class Metrics:
    def __init__(self,contract,initial):
        self.defs=contract["metrics"];self.initial=initial;self.previous=initial;self.stats={}
    def sample(self,s):
        from .living import evaluate
        for m in self.defs:
            value=evaluate(m["expression"],{"s":s,"prev":self.previous,"initial":self.initial})
            boolean=m["reduce"] in ("duration","longest","transitions")
            if boolean and type(value) is not bool:raise ValueError("boolean metric required: "+m["name"])
            if not boolean and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)):raise ValueError("finite numeric metric required: "+m["name"])
            a=self.stats.setdefault(m["name"],{"count":0,"sum":0,"min":float('inf'),"max":-float('inf'),"last":False,"run":0,"longest":0,"transitions":0})
            a["count"]+=1;a["sum"]+=value;a["min"]=min(a["min"],value);a["max"]=max(a["max"],value)
            a["run"]=a["run"]+1 if value else 0;a["longest"]=max(a["longest"],a["run"]);a["transitions"]+=int(bool(value) and not a["last"]);a["last"]=value
        self.previous=s
    def values(self):
        out={}
        for m in self.defs:
            if m["name"] not in self.stats:continue
            a=self.stats[m["name"]];r=m["reduce"]
            out[m["name"]]=a["sum"]/a["count"] if r=="mean" else a["sum"]/60 if r in ("integral","duration") else a["longest"]/60 if r=="longest" else a[r]
        return out


def supports(world):
    nodes=set(world["nodes"])|{p["id"] for p in world["appendages"]}
    norm=lambda x:'self' if x.removeprefix('self:') in nodes else x
    graph={};roots={'world'}|{o["id"] for o in world["objects"] if o.get("motion")=="static"}
    for j in world["mechanisms"]+world["ropes"]:
        a,b=norm(j["a"]),norm(j["b"]);graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
    seen={'self'};pending=['self']
    while pending:
        for b in graph.get(pending.pop(),set())-seen:seen.add(b);pending.append(b)
    return len(seen&roots)+int(world["body_control"].get("stage_rig",False))


def assess(world,id,cancelled=lambda:False,require_dependencies=True):
    from .living import trial,evaluate,sensors
    c=world["learning"]["skills"][id]
    blocked=[d for d in c["depends"] if statuses(world)[d]["status"]!="mastered"]
    if blocked and require_dependencies:return {"passed":False,"guards_pass":False,"score":None,"cases":[],"error":"unverified prerequisites: "+', '.join(blocked),"binding":binding(world,id)}
    rows=[]
    for case in c["cases"]:
        if cancelled():raise ValueError("skill evaluation cancelled")
        w=copy.deepcopy(world);name=c["program"]
        if name in w["projects"]:w.update(active_project=name,active_policy=None)
        elif name in w["policies"]:w.update(active_policy=name,active_project=None)
        else:return {"passed":False,"guards_pass":False,"score":None,"cases":[],"error":"skill program not authored: "+name,"binding":binding(world,id)}
        from .world import fresh_world
        from .workshop import add_feet
        from .character import reshape
        w['nodes']=copy.deepcopy(world['learning']['seed']['nodes']) if case['start']=='captured' else fresh_world(w['session_id'])['nodes']
        if world['body_control']['mode']=='physical' or w.get('character'):add_feet(w)
        if w.get('character'):reshape(w)
        vx,vy=case.get('velocity',[0,0])
        for n in w['nodes'].values():n['px']=n['x']-vx/60;n['py']=n['y']-vy/60
        w.update(tick=0,project_started=0,project_state={},policy_state={},event_queue=[],motion=[],appendage_frames=[],rope_state={},mechanics_state={},articulation={},contacts={},human={},direction={},policy_error=None,project_error=None)
        w['energy']={'muscle_work':0,'motor_work':0,'power':0}
        for obj in w['objects']:
            if obj['kind']=='body':
                for k in ('x','y','angle'):obj[k]=obj.get('definition',obj).get(k,0)
                obj.update(vx=0,vy=0,angular_velocity=0)
        meter=Metrics(c,sensors(w))
        def before(clone,sim,i):
            for e in case.get('events',[]):
                if e['at']==i:clone['event_queue'].append({'id':e['id'],'source':'test'})
            for e in case.get('impulses',[]):
                if e['at']==i:
                    if sim is None:raise ValueError('test impulses require the rigid body engine')
                    body,anchor=sim.ends[e['joint']];body.apply_impulse_at_world_point(e['value'],body.local_to_world(anchor))
        r=trial(w,frames=case['frames'],cancelled=cancelled,observer=lambda clone:meter.sample(sensors(clone)),before_step=before)
        r.update(metrics=meter.values() if meter.stats else {},external_supports=supports(w),powered_motors=sum(j['type']=='motor' and j['max_force']>0 for j in w['mechanisms']),gravity=w['gravity'])
        rows.append({'id':case['id'],'split':case['split'],**grade_report(c,r)})
    numeric=[r['score'] for r in rows if r['score'] is not None]
    # Rank TRAIN cases only; validation can veto acceptance, never select parameters.
    train=[r['score'] for r in rows if r['split']=='train' and r['score'] is not None]
    score=sum(train)/len(train) if train else min(numeric) if numeric else None
    return {'passed':all(r['passed'] for r in rows),'guards_pass':all(r['guards_pass'] for r in rows),'score':score,'cases':rows,'binding':binding(world,id)}



def grade_report(contract,report):
    """Domain-neutral grading of a host-measured report; never trust model claims.

    Physics supplies the report today. File/test/deployment adapters can reuse
    this function, but must obtain their own trusted measurements and bindings.
    It is deliberately not an API accepting an LLM-supplied success report.
    """
    from .living import evaluate
    try:
        if report.get('passed') is not True:raise ValueError(report.get('error','execution report failed'))
        score=evaluate(contract['score'],{'r':report});success=evaluate(contract['success'],{'r':report})
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score):raise ValueError('fitness score must be finite numeric')
        if type(success) is not bool:raise ValueError('success must be boolean')
        guards=[evaluate(g,{'r':report}) for g in contract['guards']]
        if any(type(g) is not bool for g in guards):raise ValueError('guards must be boolean')
        checks=[]
        for m in contract['metrics']:
            target=m.get('target',{});v=report['metrics'][m['name']]
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('measured metric must be finite numeric')
            checks.append({'metric':m['name'],'value':v,'target':target,'passed':target.get('min',-1e100)<=v<=target.get('max',1e100)})
        return {'score':score,'passed':success and all(guards) and all(x['passed'] for x in checks),'guards_pass':all(guards),'success':success,'metrics':checks,
                'guards':[{'expression':g,'passed':v} for g,v in zip(contract['guards'],guards)],'report':{k:v for k,v in report.items() if k not in ('objects','ropes')}}
    except (ValueError,KeyError) as exc:
        return {'score':None,'passed':False,'guards_pass':False,'error':str(exc)[:200],'metrics':report.get('metrics',{})}

def record(world,id,result,*,applied,improved=False):
    c=world['learning']['skills'][id]
    row={**copy.deepcopy(result),'id':uuid4().hex[:12],'contract':c['version'],'at':time.time(),'applied':applied,'improved':improved,'bottleneck':next((r['id'] for r in result['cases'] if not r['passed']),result.get('error'))}
    c['attempts']=(c['attempts']+[row])[-20:];world['learning']['focus']=next_focus(world)
    return row


def handle(database,sid,args,cancelled=lambda:False):
    from .world import keys,text
    from .store import GameStore
    action=args.get('action')
    with GameStore(database) as store:original=copy.deepcopy(store.get(sid))
    if original is None:raise ValueError('game session not found')
    if action=='plan':
        candidate=copy.deepcopy(original);result=plan(candidate,args)
    elif action=='evaluate':
        keys(args,('action','skill','world_version','contract'));id=args.get('skill')
        if id not in original['learning']['skills']:raise ValueError('unknown skill; available: '+(', '.join(sorted(original['learning']['skills'])) or 'none'))
        if 'world_version' in args and args['world_version']!=original['version']:raise ValueError('world changed; refresh before evaluating')
        if 'contract' in args and args['contract']!=original['learning']['skills'][id]['version']:raise ValueError('skill contract changed; refresh before evaluating')
        if statuses(original)[id]['status']=='blocked':raise ValueError(statuses(original)[id]['reason'])
        result=assess(original,id,cancelled);candidate=copy.deepcopy(original);receipt=record(candidate,id,compact(result),applied=True)
        result={'attempt':receipt,'learning':summary(candidate)}
    elif action=='note':
        keys(args,('action','skill','attempt','hypothesis','next_change'));id=args.get('skill')
        if id not in original['learning']['skills']:raise ValueError('unknown skill; available: '+(', '.join(sorted(original['learning']['skills'])) or 'none'))
        if not any(a['id']==args.get('attempt') for a in original['learning']['skills'][id]['attempts']):raise ValueError('note must cite an existing attempt')
        for k in ('hypothesis','next_change'):text(args.get(k),500,k)
        candidate=copy.deepcopy(original);candidate['learning']['lessons']=(candidate['learning']['lessons']+[{**args,'at':time.time(),'kind':'hypothesis'}])[-24:];result={'saved':True}
    else:raise ValueError('game_train action is plan, evaluate or note')
    if cancelled():raise ValueError('training cancelled')
    from .studio import configuration
    with GameStore(database) as store:
        with store.mutation(sid) as live:
            if live['learning']!=original['learning'] or configuration(live)!=configuration(original):raise ValueError('world/learning contract changed during assessment; retry')
            live['learning']=candidate['learning']
    return result


def compact(result):
    out={k:v for k,v in result.items() if k!='cases'}
    out['cases']=[{k:v for k,v in row.items() if k!='report'} for row in result['cases']]
    return out


def save_failure(database,sid,original,id,result,candidate=None,changes=None):
    from .store import GameStore
    with GameStore(database) as store:
        with store.mutation(sid) as live:
            if live['learning']!=original['learning']:raise ValueError('learning contract changed during trial')
            receipt=record(live,id,compact(result),applied=False)
            if candidate or changes:
                from .studio import digest
                name=live['learning']['skills'][id]['program']
                source=candidate or original
                p=copy.deepcopy(source['projects'].get(name) or source['policies'].get(name) or {})
                for change in changes or []:
                    if change.get('name')!=name:continue
                    if change.get('operation')=='project' and isinstance(change.get('files'),dict):
                        files={**p.get('files',{}),**change['files']}
                        if all(isinstance(k,str) and isinstance(v,str) for k,v in files.items()) and sum(map(len,files.values()))<=48000:p['files']=files
                    if change.get('operation')=='policy' and isinstance(change.get('code'),str) and len(change['code'])<=8000:p['code']=change['code']
                if p:
                    p['version']=digest({k:v for k,v in p.items() if k!='version'})[:16]
                    live['learning']['skills'][id]['working']=p
                    receipt['candidate_hash']=p['version']
    return receipt


def progress(before,after,min_delta):
    improved=after["score"] is not None and (before["score"] is None or after["score"]>before["score"]+min_delta)
    previous={c['id']:c for c in before['cases']}
    validation_ok=all(c['score'] is not None and (previous.get(c['id'],{}).get('score') is None or c['score']>=previous[c['id']]['score']-min_delta) for c in after['cases'] if c['split']=='validation')
    accepted=after['guards_pass'] and (after['passed'] or (improved and validation_ok)) and not (before['passed'] and not after['passed'])
    return accepted,improved
