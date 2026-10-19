"""Chipmunk rigid bodies, capsule limbs, physical contacts and assisted motors.

Coordinates remain canvas coordinates (positive y down). All poses are motor
targets; they never teleport joints or objects. Objects rotate and exchange
impulses with whole limb capsules, not only eleven decorative points.
"""
from __future__ import annotations

import math
import pymunk


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


class RigidSimulator:
    def __init__(self, world):
        from .character import bone_pairs, anchors
        self.world = world
        self.space = pymunk.Space()
        self.space.gravity = (0, world["gravity"])
        self.space.iterations = max(36 if world["ropes"] else 12,world["material"]["iterations"]*2)
        self.space.collision_slop = .15
        self.space.damping = .96
        self.segments = {}
        self.ends = {}
        self.objects = {}
        self.contact_ids = set()
        self.ground_contacts = set()
        self.joint_contacts = set()
        self.support_points=[];self.contact_impulse=0;self.external_contact=set()
        self.grip = None
        self._shape_objects = {}
        self._shape_joints = {}
        for a, b in (((0, 540), (1000, 540)), ((0, 0), (0, 540)), ((1000, 0), (1000, 540))):
            floor = pymunk.Segment(self.space.static_body, a, b, 1)
            floor.friction = 1.1 * world["material"]["friction"] / .82
            self.space.add(floor)
        nodes = world["nodes"]
        pairs=bone_pairs(world)
        character=world.get("character")
        self.physical=world["body_control"]["mode"]=="physical"
        for a, b in pairs:
            if a == "head":
                continue
            pa, pb = pymunk.Vec2d(nodes[a]["x"], nodes[a]["y"]), pymunk.Vec2d(nodes[b]["x"], nodes[b]["y"])
            length = (pb - pa).length
            spec=character["bones"][b] if character else None
            radius=spec["radius"] if spec else 4
            mass = spec["mass"] if spec else 4.0 if b == "hip" else .8 if "knee" in b else .55
            heel=spec.get("heel",0) if spec and b.endswith("toe") else 0
            body = pymunk.Body(mass, pymunk.moment_for_segment(mass, (-length / 2-heel, 0), (length / 2, 0), radius))
            body.position = (pa + pb) / 2
            body.angle = (pb - pa).angle
            if self.physical:
                saved=world["articulation"].get(b,{})
                if b=="hip" and world["articulation"].get("head"):
                    h=world["articulation"]["head"];saved={"world_angle":h["world_angle"]-h["angle"]}
                old_angle=saved.get("world_angle",body.angle)
                body.angle+=round((old_angle-body.angle)/(2*math.pi))*2*math.pi
            body.velocity = ((nodes[a]["x"] - nodes[a]["px"] + nodes[b]["x"] - nodes[b]["px"]) * 30,
                             (nodes[a]["y"] - nodes[a]["py"] + nodes[b]["y"] - nodes[b]["py"]) * 30)
            delta=pb-pa
            va=pymunk.Vec2d((nodes[a]["x"]-nodes[a]["px"])*60,(nodes[a]["y"]-nodes[a]["py"])*60)
            vb=pymunk.Vec2d((nodes[b]["x"]-nodes[b]["px"])*60,(nodes[b]["y"]-nodes[b]["py"])*60)
            body.angular_velocity=delta.cross(vb-va)/max(.01,length**2)
            capsule = pymunk.Segment(body, (-length / 2-heel, 0), (length / 2, 0), radius)
            if character and b=="hip":
                sw=max(radius*2,character["shoulder_width"]);hw=max(radius,character["hip_width"])
                vertices=[(-length/2,-radius*.4),(-length/2+8,-sw/2),(length/2-3,-hw/2),(length/2+radius*.3,0),(length/2-3,hw/2),(-length/2+8,sw/2),(-length/2,radius*.4)]
                capsule=pymunk.Poly(body,vertices);body.moment=pymunk.moment_for_poly(mass,vertices)
            capsule.friction = (1.25 if "foot" in b else .65)*world["material"]["friction"]/.82
            capsule.filter = pymunk.ShapeFilter(group=0 if world["body_control"]["self_collision"] else 1, categories=1)
            self.space.add(body, capsule)
            self.segments[b] = (body, length, a, b)
            self._shape_joints[capsule] = b
            if a not in self.ends:
                self.ends[a] = (body, (-length / 2, 0))
            self.ends[b] = (body, (length / 2, 0))
            if character and b=="hip":
                for name,point in anchors(character).items():self.ends[name]=(body,point)
        # Adjacent rigid limbs share actual pivot constraints.
        for name, (body, length, a, b) in self.segments.items():
            if b == "hip":
                continue
            parent, anchor = self.ends[a]
            pivot = pymunk.PivotJoint(parent, body, anchor, (-length / 2, 0))
            pivot.collide_bodies = False
            self.space.add(pivot)
        head_mass=character["head_mass"] if character else 1.0
        head_radius=character["head_radius"] if character else 12
        neck_length=character["neck_length"] if character else 20
        head = pymunk.Body(head_mass, pymunk.moment_for_circle(head_mass, 0, head_radius))
        head.position = (nodes["head"]["x"], nodes["head"]["y"])
        if self.physical:
            head.angle=math.atan2(nodes["neck"]["y"]-nodes["head"]["y"],nodes["neck"]["x"]-nodes["head"]["x"])-math.pi/2
            delta=pymunk.Vec2d(nodes["neck"]["x"]-nodes["head"]["x"],nodes["neck"]["y"]-nodes["head"]["y"])
            dv=pymunk.Vec2d((nodes["neck"]["x"]-nodes["neck"]["px"]-nodes["head"]["x"]+nodes["head"]["px"])*60,(nodes["neck"]["y"]-nodes["neck"]["py"]-nodes["head"]["y"]+nodes["head"]["py"])*60)
            head.angular_velocity=delta.cross(dv)/max(.01,delta.length_squared)
            old_angle=world["articulation"].get("head",{}).get("world_angle",head.angle)
            head.angle+=round((old_angle-head.angle)/(2*math.pi))*2*math.pi
        head.velocity = ((nodes["head"]["x"] - nodes["head"]["px"]) * 60, (nodes["head"]["y"] - nodes["head"]["py"]) * 60)
        shape = pymunk.Circle(head, head_radius)
        shape.filter = pymunk.ShapeFilter(group=0 if world["body_control"]["self_collision"] else 1, categories=1)
        shape.friction = .5
        self.space.add(head, shape)
        parent, anchor = self.ends["neck"]
        if self.physical:
            neck=pymunk.PivotJoint(parent,head,anchor,(0,neck_length));neck.collide_bodies=False
        else:
            neck = pymunk.PinJoint(parent, head, anchor, (0, 0))
            neck.distance = neck_length
        self.space.add(neck)
        self.ends["head"] = (head, (0, 0))
        self._shape_joints[shape] = "head"
        self.springs = {}
        for name, (body, length, a, b) in self.segments.items():
            if self.physical:continue
            frequency = 1800 if name == "hip" else 2800 if "knee" in name or "foot" in name else 500
            spring = pymunk.DampedRotarySpring(self.space.static_body, body, -body.angle, body.moment * frequency, body.moment * 90)
            self.space.add(spring)
            self.springs[name] = spring
        self.appendages = {}
        self.extra_ends = {}
        previous = {part[0]:part for part in world.get("appendage_frames",[])}
        for part in world.get("appendages",[]):
            parent, anchor = (self.extra_ends | self.ends)[part["parent"]]
            start = parent.local_to_world(anchor)
            old = previous.get(part["id"])
            angle = math.atan2(old[2][1]-old[1][1],old[2][0]-old[1][0]) if old else part["angle"]
            length, mass, radius = part["length"],part["mass"],part["radius"]
            body = pymunk.Body(mass,pymunk.moment_for_segment(mass,(-length/2,0),(length/2,0),radius))
            body.position = start+pymunk.Vec2d(math.cos(angle),math.sin(angle))*length/2
            body.angle = angle
            body.velocity = parent.velocity_at_world_point(start)
            shape = pymunk.Segment(body,(-length/2,0),(length/2,0),radius)
            shape.filter=pymunk.ShapeFilter(group=1,categories=1);shape.friction=.65
            pivot=pymunk.PivotJoint(parent,body,anchor,(-length/2,0))
            motor=None if self.physical else pymunk.DampedRotarySpring(self.space.static_body,body,-angle,body.moment*450,body.moment*35)
            self.space.add(body,shape,pivot)
            if motor:self.space.add(motor)
            self.appendages[part["id"]]=(body,length,motor,part)
            self.extra_ends[part["id"]]=(body,(length/2,0))
            self._shape_joints[shape]=part["id"]
        from .embodiment import Embodiment
        from .mechanics import Mechanics
        self.muscle_system=Embodiment(self)
        self.mechanics=Mechanics(self)
        parts=[(body,{a,b}) for body,length,a,b in self.segments.values()]+[(head,{"head","neck"})]+[(body,{part["parent"],part["id"]}) for body,length,motor,part in self.appendages.values()]
        self.adjacent={frozenset((a,b)) for i,(a,nodes) in enumerate(parts) for b,other in parts[i+1:] if nodes&other}
        self.space.on_collision(None,None,pre_solve=self._filter_contact,post_solve=self._contact)
        self.substeps=world["body_control"].get("solver_substeps",4)
        from .dynamics import measure
        measure(self,1/60)

    def _filter_contact(self,arbiter,space,data):
        a,b=arbiter.shapes
        if a in self._shape_joints and b in self._shape_joints and frozenset((a.body,b.body)) in self.adjacent:
            arbiter.process_collision=False

    def _contact(self, arbiter, space, data):
        a, b = arbiter.shapes
        for actor, other in ((a, b), (b, a)):
            if actor not in self._shape_joints:
                continue
            name = self._shape_joints[actor]
            if other not in self._shape_joints:
                self.external_contact.add(name)
                self.contact_impulse+=abs(arbiter.total_impulse.y)
            self.joint_contacts.add(name)
            if name.endswith("foot") or name.endswith("toe"):
                # Contact must support the foot from below, not be a side wall.
                p = (self.ends | self.extra_ends)[name][0].local_to_world((self.ends | self.extra_ends)[name][1])
                if other.point_query((p.x, p.y + 5)).distance < 2:
                    self.ground_contacts.add(name)
                    for point in arbiter.contact_point_set.points:self.support_points.append((point.point_a.x+point.point_b.x)/2)
            if other in self._shape_objects:
                self.contact_ids.add(self._shape_objects[other])

    def step(self, control, dt=None):
        from .world import OFFSETS, DT
        dt=DT if dt is None else dt
        self.substeps=self.world["body_control"].get("solver_substeps",4) if self.physical or self.world["ropes"] else 2
        w = self.world
        self.space.gravity = (0, w["gravity"])
        self.space.damping = w["body_control"]["air_damping"] if self.physical else clamp(w["material"]["damping"]**4,.5,.999)
        self.muscle_system.prepare(control)
        from .cinema import apply_rig
        self.mechanics.world=w
        self.mechanics.control(control)
        for body in self.space.bodies:
            if not self.physical and body.body_type==pymunk.Body.DYNAMIC:
                body.velocity=(body.velocity.x,body.velocity.y*w["material"]["vertical_damping"])
        drive = control.get("drive", 0)
        human = w.get("human", {})
        if human.get("until", 0) >= w["tick"]:
            drive = human.get("drive", drive)
        pose = {name: list(value) for name, value in OFFSETS.items()}
        for side in ("left","right"):
            if side+"_toe" in w["nodes"]:pose[side+"_toe"]=[pose[side+"_foot"][0]+13,pose[side+"_foot"][1]]
        phase = w["tick"] * DT * (5 + abs(drive) * 4)
        for side, offset in (("left", 0), ("right", math.pi)):
            swing = math.sin(phase + offset)
            pose[side + "_foot"][0] += swing * w["controller"]["stride"] * abs(drive)
            pose[side + "_foot"][1] -= max(0, swing) * 42 * abs(drive)
            pose[side + "_knee"][0] += swing * 14 * abs(drive)
            pose[side + "_hand"][0] -= swing * 10 * abs(drive)
        if w.get("character"):
            for side in ("left","right"):
                for name in (side+"_shoulder",side+"_pelvis"):
                    pose[name]=[w["nodes"][name]["x"]-w["nodes"]["hip"]["x"],w["nodes"][name]["y"]-w["nodes"]["hip"]["y"]]
        pose.update(control.get("pose", {}))
        strength = w["controller"]["balance"] * w["material"]["pose_strength"] / .08
        for name, spring in self.springs.items():
            body, length, a, b = self.segments[name]
            angle = math.atan2(pose[b][1] - pose[a][1], pose[b][0] - pose[a][0])
            angle += round((body.angle - angle) / (2 * math.pi)) * 2 * math.pi
            spring.rest_angle = -angle
            spring.stiffness = body.moment * (1800 if name == "hip" else 2800 if "knee" in name or "foot" in name else 500) * strength * w["material"]["stiffness"]
            spring.damping = body.moment * 90 * min(1, strength)
        for name,(body,length,motor,part) in self.appendages.items():
            if motor is None:continue
            angle=control.get("appendage_pose",{}).get(name,part["angle"])
            angle+=round((body.angle-angle)/(2*math.pi))*2*math.pi
            motor.rest_angle=-angle
        torso = self.segments["hip"][0]
        total_mass = sum(b.mass for b in self.space.bodies if b.body_type == pymunk.Body.DYNAMIC and b not in self.objects.values())
        grounded = bool(self.ground_contacts) or any(p["y"] > 530 for key, p in w["nodes"].items() if key.endswith("foot"))
        desired = drive * w["controller"]["speed"]
        if not self.physical:torso.apply_force_at_world_point((clamp((desired - torso.velocity.x) * total_mass * (35 if grounded else 1.5), -18000, 18000), 0), torso.position)
        if not self.physical and (control.get("jump") or human.get("jump")) and grounded:
            for body in self.space.bodies:
                if body.body_type == pymunk.Body.DYNAMIC and body not in self.objects.values():
                    body.velocity = (body.velocity.x, -w["controller"]["jump"])
            if human.get("jump"):
                human["jump"] = False
        # Head posture is a physical, damped force subject to the neck constraint.
        hip = self.ends["hip"][0].local_to_world(self.ends["hip"][1])
        head = self.ends["head"][0]
        target = hip + pymunk.Vec2d(*pose["head"])
        force = (target - head.position) * 900 - head.velocity * 65
        if not self.physical:head.apply_force_at_world_point(force * strength, head.position)
        for name, vector in control.get("forces", {}).items():
            body, anchor = self.ends[name]
            body.apply_force_at_world_point((vector[0] * body.mass, vector[1] * body.mass), body.local_to_world(anchor))
        for name, vector in control.get("object_forces", {}).items():
            body = self.objects[name]
            body.apply_force_at_world_point(vector, body.position)
        grab = control.get("grip")
        target_id = grab.get("object") if isinstance(grab, dict) else None
        if self.grip and (not target_id or self.grip[0] != target_id):
            self.space.remove(self.grip[1])
            self.grip = None
        if target_id in self.objects and not self.grip:
            hand_name = grab.get("hand", "right_hand")
            body, anchor = self.ends.get(hand_name, self.ends["right_hand"])
            point = body.local_to_world(anchor)
            obj = self.objects[target_id]
            distance=min((shape.point_query(point).distance for shape in obj.shapes),default=float("inf"))
            reachable=distance<=6 if self.physical else (obj.position-point).length<55
            if reachable:
                joint = pymunk.PivotJoint(body, obj, point)
                joint.max_force = 4500
                self.space.add(joint)
                self.grip = (target_id, joint)
        pointer = human.get("pointer")
        grabbed = self.objects.get(human.get("object"))
        if pointer and grabbed:
            f = (pymunk.Vec2d(*pointer) - grabbed.position) * 65 - grabbed.velocity * 9
            grabbed.apply_force_at_world_point((clamp(f.x, -8000, 8000), clamp(f.y, -8000, 8000)), grabbed.position)
        self.support_points=[];self.contact_impulse=0;self.external_contact=set()
        self.contact_ids.clear()
        self.ground_contacts.clear()
        self.joint_contacts.clear()
        self.mechanics.begin_step()
        for _ in range(self.substeps):
            self.muscle_system.apply(dt/self.substeps)
            apply_rig(self,control.get("rig"),dt/self.substeps)
            self.space.step(dt/self.substeps)
            self.mechanics.after_substep()
        self.muscle_system.record(dt)
        self.mechanics.record(dt)
        for name, (body, local) in self.ends.items():
            p = body.local_to_world(local)
            velocity = body.velocity_at_world_point(p)
            w["nodes"][name].update(x=p.x, y=p.y, px=p.x - velocity.x * DT, py=p.y - velocity.y * DT)
        for obj in w["objects"]:
            if obj["id"] in self.objects:
                b = self.objects[obj["id"]]
                obj.update(x=b.position.x, y=b.position.y, vx=b.velocity.x, vy=b.velocity.y,
                           angle=b.angle, angular_velocity=b.angular_velocity)
        w["appendage_frames"] = [[name,list(body.local_to_world((-length/2,0))),list(body.local_to_world((length/2,0)))] for name,(body,length,_,_) in self.appendages.items()]
        w["contacts"] = {"objects": sorted(self.contact_ids), "support": sorted(self.ground_contacts),
                         "joints": sorted(self.joint_contacts), "grip": self.grip[0] if self.grip else None}
        from .dynamics import measure
        measure(self,dt)
        w["tick"] += 1 if dt==DT else dt/DT
