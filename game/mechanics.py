"""Rigid assemblies, material contacts and discretized, colliding rope chains."""
from __future__ import annotations
import math
import pymunk


class Mechanics:
    def __init__(self, sim):
        self.sim=sim;self.world=sim.world;self.space=sim.space
        self.constraints={};self.ropes={}
        for obj in self.world["objects"]:
            if obj["kind"]=="body":
                shape=obj["shape"];mass=obj["mass"]
                moment=pymunk.moment_for_circle(mass,0,obj["radius"]) if shape=="circle" else pymunk.moment_for_poly(mass,obj["vertices"]) if shape=="polygon" else pymunk.moment_for_box(mass,(obj["width"],obj["height"]))
                body=pymunk.Body(body_type=pymunk.Body.STATIC) if obj.get("motion")=="static" else pymunk.Body(mass,moment)
                body.position=(obj["x"],obj["y"]);body.angle=obj.get("angle",0)
                if body.body_type==pymunk.Body.DYNAMIC:
                    body.velocity=(obj.get("vx",0),obj.get("vy",0));body.angular_velocity=obj.get("angular_velocity",0)
                s=pymunk.Circle(body,obj["radius"]) if shape=="circle" else pymunk.Poly(body,obj["vertices"],radius=.5) if shape=="polygon" else pymunk.Poly.create_box(body,(obj["width"],obj["height"]),radius=1)
                s.elasticity=obj["restitution"];s.friction=obj.get("friction",.85)
                self.space.add(body,s);sim.objects[obj["id"]]=body;sim._shape_objects[s]=obj["id"]
            elif obj["kind"]=="block":
                body=pymunk.Body(body_type=pymunk.Body.STATIC);body.position=(obj["x"]+obj["width"]/2,obj["y"]+obj["height"]/2)
                s=pymunk.Poly.create_box(body,(obj["width"],obj["height"]),radius=1);s.friction=1.1;self.space.add(body,s)
        for j in self.world["mechanisms"]:self.add_joint(j)
        for i,r in enumerate(self.world["ropes"]):self.add_rope(r,i)

    def endpoint(self,name,anchor=None):
        if name=="world":return self.space.static_body,pymunk.Vec2d(*(anchor or (0,0)))
        key=name.removeprefix("self:")
        if key in self.sim.ends or key in self.sim.extra_ends:
            body,local=(self.sim.ends|self.sim.extra_ends)[key]
            return body,pymunk.Vec2d(*local)+pymunk.Vec2d(*(anchor or (0,0)))
        if name not in self.sim.objects:raise ValueError("unknown physical endpoint: "+name)
        return self.sim.objects[name],pymunk.Vec2d(*(anchor or (0,0)))

    def add_joint(self,j):
        a,pa=self.endpoint(j["a"],j.get("anchor_a"));b,pb=self.endpoint(j["b"],j.get("anchor_b"))
        if a is b:raise ValueError("constraint endpoints resolve to the same rigid body")
        kind=j["type"]
        if kind=="pivot":c=pymunk.PivotJoint(a,b,j["anchor"]) if "anchor" in j else pymunk.PivotJoint(a,b,pa,pb)
        elif kind=="pin":c=pymunk.PinJoint(a,b,pa,pb);c.distance=j["length"]
        elif kind=="slide":c=pymunk.SlideJoint(a,b,pa,pb,j["min"],j["max"])
        elif kind=="spring":c=pymunk.DampedSpring(a,b,pa,pb,j["length"],j["stiffness"],j["damping"])
        elif kind=="motor":c=pymunk.SimpleMotor(a,b,j["rate"])
        elif kind=="gear":c=pymunk.GearJoint(a,b,j["phase"],j["ratio"])
        elif kind=="rotary_limit":c=pymunk.RotaryLimitJoint(a,b,j["min"],j["max"])
        elif kind=="rotary_spring":c=pymunk.DampedRotarySpring(a,b,j["phase"],j["stiffness"],j["damping"])
        else:
            c=pymunk.PivotJoint(a,b,pa,pb)
            rotation=pymunk.GearJoint(a,b,b.angle-a.angle,1)
            rotation.max_force=j["max_force"];rotation.collide_bodies=j.get("collide",False);self.space.add(rotation)
            self.constraints[j["id"]+":rotation"]=(rotation,j,pa,pb)
        if hasattr(c,"anchor_a"):
            pa,pb=c.anchor_a,c.anchor_b
        elif a is self.space.static_body:
            pa=a.world_to_local(b.position)
        c.max_force=j["max_force"];c.collide_bodies=j.get("collide",False)
        self.space.add(c);self.constraints[j["id"]]=(c,j,pa,pb)
        if self.world.get("mechanics_state",{}).get(j["id"],{}).get("broken"):self.space.remove(c)

    def add_rope(self,r,index):
        a,pa=self.endpoint(r["a"],r.get("anchor_a"));b,pb=self.endpoint(r["b"],r.get("anchor_b"))
        route=[pymunk.Vec2d(*p) for p in r["points"]]
        saved=self.world["rope_state"].get(r["id"])
        pieces=[]
        if not saved:
            route[0]=a.local_to_world(pa);route[-1]=b.local_to_world(pb)
            for start,end in zip(route,route[1:]):
                count=max(1,math.ceil((end-start).length/r["segment_length"]))
                for i in range(count):pieces.append((start+(end-start)*i/count,start+(end-start)*(i+1)/count))
        else:
            for x,y,angle,vx,vy,omega,length in saved["bodies"]:
                delta=pymunk.Vec2d(math.cos(angle),math.sin(angle))*length/2;center=pymunk.Vec2d(x,y)
                pieces.append((center-delta,center+delta))
        if len(pieces)>128:raise ValueError("moved rope endpoints exceed runtime link budget")
        for endpoint in (a,b):
            for shape in endpoint.shapes:
                f=shape.filter
                shape.filter=pymunk.ShapeFilter(group=f.group,categories=f.categories,mask=f.mask&~(1<<(index+3)))
        bodies=[];lengths=[];joints=[]
        for i,(start,end) in enumerate(pieces):
            length=max(.2,(end-start).length);mass=max(.001,r["mass_per_meter"]*length/100)
            body=pymunk.Body(mass,pymunk.moment_for_segment(mass,(-length/2,0),(length/2,0),r["radius"]))
            body.position=(start+end)/2;body.angle=(end-start).angle
            if saved:body.velocity=saved["bodies"][i][3:5];body.angular_velocity=saved["bodies"][i][5]
            s=pymunk.Segment(body,(-length/2,0),(length/2,0),r["radius"]);s.friction=.5;s.filter=pymunk.ShapeFilter(group=100+index,categories=1<<(index+3))
            self.space.add(body,s);bodies.append(body);lengths.append(length)
            previous=a if i==0 else bodies[i-1];anchor=pa if i==0 else (lengths[i-1]/2,0)
            j=pymunk.PivotJoint(previous,body,anchor,(-length/2,0));j.collide_bodies=False;j.max_force=r["break_force"]*1.25;self.space.add(j);joints.append(j)
        j=pymunk.PivotJoint(bodies[-1],b,(lengths[-1]/2,0),pb);j.collide_bodies=False;j.max_force=r["break_force"]*1.25;self.space.add(j);joints.append(j)
        broken=saved.get("broken") if saved else None
        if broken is not None and broken<len(joints):self.space.remove(joints[broken])
        self.ropes[r["id"]]={"definition":r,"bodies":bodies,"lengths":lengths,"joints":joints,"broken":broken}

    def control(self,output):
        for name,(c,j,_,_) in self.constraints.items():
            if j["type"]!="motor" or name.endswith(":rotation") or c not in self.space.constraints:continue
            settings=output.get("joint_controls",{}).get(name,{})
            c.rate=settings.get("rate",j["rate"]);c.max_force=settings.get("max_force",j["max_force"])

    def begin_step(self):
        self.impulses={};self.motor_work=0

    def after_substep(self):
        for c in self.space.constraints:self.impulses[c]=self.impulses.get(c,0)+abs(c.impulse)
        for c,j,_,_ in self.constraints.values():
            if j["type"]=="motor" and c in self.space.constraints:self.motor_work+=abs(c.impulse*(c.b.angular_velocity-c.a.angular_velocity))

    def record(self,dt):
        state={};motor_work=0
        for name,(c,j,pa,pb) in self.constraints.items():
            active=c in self.space.constraints
            force=self.impulses.get(c,0)/dt if active else 0
            if active and force>j.get("break_force",200000):self.space.remove(c);active=False
            state[name]={"type":j["type"],"load":round(force,2),"broken":not active,"a":list(c.a.local_to_world(pa)),"b":list(c.b.local_to_world(pb))}
            if j["type"]=="motor" and active:motor_work+=abs(c.impulse*(c.b.angular_velocity-c.a.angular_velocity))
        self.world["mechanics_state"]=state
        self.world["energy"]["motor_work"]+=self.motor_work/10000
        frames=[]
        for name,r in self.ropes.items():
            impulses=[self.impulses.get(c,0)/dt if c in self.space.constraints else 0 for c in r["joints"]]
            tension=max(impulses,default=0)
            if r["broken"] is None and tension>r["definition"]["break_force"]:
                r["broken"]=impulses.index(tension);self.space.remove(r["joints"][r["broken"]])
            bodies=r["bodies"];lengths=r["lengths"]
            self.world["rope_state"][name]={"broken":r["broken"],"bodies":[[b.position.x,b.position.y,b.angle,b.velocity.x,b.velocity.y,b.angular_velocity,length] for b,length in zip(bodies,lengths)]}
            frames.append({"id":name,"color":r["definition"]["color"],"radius":r["definition"]["radius"],"segments":[[list(b.local_to_world((-length/2,0))),list(b.local_to_world((length/2,0)))] for b,length in zip(bodies,lengths)],"length":sum(lengths),"tension":round(tension,2),"broken":r["broken"] is not None})
        self.world["rope_frames"]=frames
