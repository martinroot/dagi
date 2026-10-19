"""Unassisted articulation: bounded internal torques and explicit relative servos."""
from __future__ import annotations
import math
import pymunk


def limits(world):
    result={"head":(-2.3,-.8,9000)}
    for side in ("left","right"):
        result[side+"_elbow"]=(-2.9,2.9,35000)
        result[side+"_hand"]=(-2.8,.4,22000) if side=="left" else (-.4,2.8,22000)
        result[side+"_knee"]=(-1.9,1.9,90000)
        result[side+"_foot"]=(-2.6,.4,65000)
        if side+"_toe" in world["nodes"]:result[side+"_toe"]=(-2.5,-.3,30000)
    for p in world["appendages"]:result[p["id"]]=(-3.14,3.14,15000)
    return result


def validate(world,output):
    from .world import keys,number
    physical=world["body_control"]["mode"]=="physical"
    if physical and (output.get("drive",0) or output.get("jump") or any(output.get(k) for k in ("pose","forces","object_forces","appendage_pose"))):
        raise ValueError("physical mode has no automatic drive/jump/pose/free forces; use muscles, relative servos and mechanism motors")
    if "rig" in output:
        from .cinema import validate_rig
        validate_rig(world,output["rig"])
    info=limits(world)
    muscles=output.get("muscles",{});servos=output.get("servos",{})
    for field,values in (("muscles",muscles),("servos",servos)):
        if not isinstance(values,dict) or set(values)-set(info):raise ValueError(field+" references an unknown articulated joint")
    for value in muscles.values():number(value,-1,1,"muscle effort")
    for name,v in servos.items():
        keys(v,("angle","stiffness","damping","max_torque"));lo,hi,maximum=info[name]
        number(v.get("angle"),lo,hi,"relative joint angle")
        for k,d,a,b in (("stiffness",12000,0,300000),("damping",180,0,10000),("max_torque",maximum*world["body_control"]["muscle_scale"],0,maximum*world["body_control"]["muscle_scale"])):number(v.get(k,d),a,b,k)
    commands=output.get("joint_controls",{})
    motors={j["id"]:j for j in world["mechanisms"] if j["type"]=="motor"}
    if not isinstance(commands,dict) or set(commands)-set(motors):raise ValueError("joint_controls references an unknown mechanism motor")
    for name,v in commands.items():
        keys(v,("rate","max_force"))
        if "rate" in v:number(v["rate"],-30,30,"motor rate")
        if "max_force" in v:number(v["max_force"],0,motors[name]["max_force"],"motor torque cap")


class Embodiment:
    def __init__(self,sim):
        self.sim=sim;self.joints={};self.torques={};self.activations={k:v.get("torque",0) for k,v in sim.world.get("muscle_state",{}).items()};self.step_work=0;self.negative_work=0
        info=limits(sim.world)
        for name,(body,length,a,b) in sim.segments.items():
            if name=="hip":continue
            parent,_=sim.ends[a]
            self.joints[name]=(parent,body,*info[name])
        self.joints["head"]=(sim.ends["neck"][0],sim.ends["head"][0],*info["head"])
        for name,(body,length,motor,part) in sim.appendages.items():
            parent,_=(sim.ends|sim.extra_ends)[part["parent"]]
            self.joints[name]=(parent,body,*info[name])
        if sim.world["body_control"]["mode"]=="physical":
            for parent,body,lo,hi,maximum in self.joints.values():
                joint=pymunk.RotaryLimitJoint(parent,body,lo,hi);joint.collide_bodies=False;sim.space.add(joint)
        self.record(0)

    def prepare(self,output):
        w=self.sim.world;efforts=dict(output.get("muscles",{}))
        if w["human"].get("until",-1)>=w["tick"]:efforts.update(w["human"].get("muscles",{}))
        self.step_work=0;self.negative_work=0
        self.efforts=efforts;self.servos=output.get("servos",{})
        self.refresh()

    def refresh(self):
        w=self.sim.world;efforts=self.efforts
        self.torques={}
        for name,(parent,body,lo,hi,maximum) in self.joints.items():
            limit=maximum*w["body_control"]["muscle_scale"]
            torque=efforts.get(name,0)*limit
            servo=self.servos.get(name)
            if servo:
                error=servo["angle"]-(body.angle-parent.angle)
                torque+=error*servo.get("stiffness",12000)-(body.angular_velocity-parent.angular_velocity)*servo.get("damping",180)
                limit=min(limit,servo.get("max_torque",limit))
            self.torques[name]=max(-limit,min(limit,torque))

    def apply(self,dt=1/240):
        self.refresh()
        w=self.sim.world
        for name,(parent,body,lo,hi,maximum) in self.joints.items():
            passive=w["body_control"]["joint_damping"]*(body.angular_velocity-parent.angular_velocity) if w["body_control"]["mode"]=="physical" else 0
            requested=self.torques.get(name,0)
            if w["body_control"].get("muscle_dynamics"):
                # Activation/relaxation lag; no torque or support from the world.
                previous=self.activations.get(name,0)
                requested=previous+(requested-previous)*(1-math.exp(-dt/.018))
                self.activations[name]=requested
            torque=requested-passive
            self.torques[name]=requested
            power=requested*(body.angular_velocity-parent.angular_velocity)
            self.step_work+=max(0,power)*dt/10000;self.negative_work+=max(0,-power)*dt/10000
            body.torque+=torque;parent.torque-=torque

    def record(self,dt):
        state={};positive_work=0;muscles={}
        for name,(parent,body,lo,hi,maximum) in self.joints.items():
            velocity=body.angular_velocity-parent.angular_velocity;torque=self.torques.get(name,0)
            maximum*=self.sim.world["body_control"]["muscle_scale"]
            muscles[name]={"torque":torque,"activation":abs(torque)/maximum,"shortening":torque*velocity>0,"power":torque*velocity/10000}
            state[name]={"world_angle":body.angle,"angle":body.angle-parent.angle,"velocity":velocity,"min":lo,"max":hi,"max_torque":maximum,"torque":torque}
        self.sim.world["articulation"]=state
        self.sim.world["muscle_state"]=muscles
        positive_work=self.step_work
        self.sim.world["energy"]["muscle_work"]+=positive_work
        self.sim.world["energy"]["negative_work"]=self.sim.world["energy"].get("negative_work",0)+self.negative_work
        self.sim.world["energy"]["power"]=positive_work/dt if dt else 0
