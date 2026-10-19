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
        from .world import PAIRS
        self.world = world
        self.space = pymunk.Space()
        self.space.gravity = (0, world["gravity"])
        self.space.iterations = max(12,world["material"]["iterations"]*2)
        self.space.collision_slop = .15
        self.space.damping = .96
        self.segments = {}
        self.ends = {}
        self.objects = {}
        self.contact_ids = set()
        self.ground_contacts = set()
        self.joint_contacts = set()
        self.grip = None
        self._shape_objects = {}
        self._shape_joints = {}
        for a, b in (((0, 540), (1000, 540)), ((0, 0), (0, 540)), ((1000, 0), (1000, 540))):
            floor = pymunk.Segment(self.space.static_body, a, b, 1)
            floor.friction = 1.1 * world["material"]["friction"] / .82
            self.space.add(floor)
        nodes = world["nodes"]
        for a, b in PAIRS:
            if a == "head":
                continue
            pa, pb = pymunk.Vec2d(nodes[a]["x"], nodes[a]["y"]), pymunk.Vec2d(nodes[b]["x"], nodes[b]["y"])
            length = (pb - pa).length
            mass = 4.0 if b == "hip" else .8 if "knee" in b else .55
            body = pymunk.Body(mass, pymunk.moment_for_segment(mass, (-length / 2, 0), (length / 2, 0), 4))
            body.position = (pa + pb) / 2
            body.angle = (pb - pa).angle
            body.velocity = ((nodes[a]["x"] - nodes[a]["px"] + nodes[b]["x"] - nodes[b]["px"]) * 30,
                             (nodes[a]["y"] - nodes[a]["py"] + nodes[b]["y"] - nodes[b]["py"]) * 30)
            capsule = pymunk.Segment(body, (-length / 2, 0), (length / 2, 0), 4)
            capsule.friction = (1.25 if "foot" in b else .65)*world["material"]["friction"]/.82
            capsule.filter = pymunk.ShapeFilter(group=1, categories=1)
            self.space.add(body, capsule)
            self.segments[b] = (body, length, a, b)
            self._shape_joints[capsule] = b
            if a not in self.ends:
                self.ends[a] = (body, (-length / 2, 0))
            self.ends[b] = (body, (length / 2, 0))
        # Adjacent rigid limbs share actual pivot constraints.
        for name, (body, length, a, b) in self.segments.items():
            if b == "hip":
                continue
            parent, anchor = self.ends[a]
            pivot = pymunk.PivotJoint(parent, body, anchor, (-length / 2, 0))
            pivot.collide_bodies = False
            self.space.add(pivot)
        head = pymunk.Body(1.0, pymunk.moment_for_circle(1.0, 0, 12))
        head.position = (nodes["head"]["x"], nodes["head"]["y"])
        head.velocity = ((nodes["head"]["x"] - nodes["head"]["px"]) * 60, (nodes["head"]["y"] - nodes["head"]["py"]) * 60)
        shape = pymunk.Circle(head, 12)
        shape.filter = pymunk.ShapeFilter(group=1, categories=1)
        shape.friction = .5
        self.space.add(head, shape)
        parent, anchor = self.ends["neck"]
        neck = pymunk.PinJoint(parent, head, anchor, (0, 0))
        neck.distance = 20
        self.space.add(neck)
        self.ends["head"] = (head, (0, 0))
        self._shape_joints[shape] = "head"
        self.springs = {}
        for name, (body, length, a, b) in self.segments.items():
            frequency = 1800 if name == "hip" else 2800 if "knee" in name or "foot" in name else 500
            spring = pymunk.DampedRotarySpring(self.space.static_body, body, -body.angle, body.moment * frequency, body.moment * 90)
            self.space.add(spring)
            self.springs[name] = spring
        for obj in world["objects"]:
            if obj["kind"] == "body":
                mass = obj["mass"]
                moment = pymunk.moment_for_circle(mass, 0, obj["radius"]) if obj["shape"] == "circle" else pymunk.moment_for_box(mass, (obj["width"], obj["height"]))
                body = pymunk.Body(mass, moment)
                body.position = (obj["x"], obj["y"])
                body.velocity = (obj.get("vx", 0), obj.get("vy", 0))
                body.angle = obj.get("angle", 0)
                body.angular_velocity = obj.get("angular_velocity", 0)
                shape = pymunk.Circle(body, obj["radius"]) if obj["shape"] == "circle" else pymunk.Poly.create_box(body, (obj["width"], obj["height"]), radius=2)
                shape.elasticity = obj["restitution"]
                shape.friction = .85
                self.space.add(body, shape)
                self.objects[obj["id"]] = body
                self._shape_objects[shape] = obj["id"]
            elif obj["kind"] == "block":
                body = pymunk.Body(body_type=pymunk.Body.STATIC)
                body.position = (obj["x"] + obj["width"] / 2, obj["y"] + obj["height"] / 2)
                shape = pymunk.Poly.create_box(body, (obj["width"], obj["height"]), radius=1)
                shape.friction = 1.1
                self.space.add(body, shape)
        self.space.on_collision(None, None, post_solve=self._contact)
        for joint in world.get("mechanisms",[]):
            a=self.space.static_body if joint["a"]=="world" else self.objects.get(joint["a"])
            b=self.space.static_body if joint["b"]=="world" else self.objects.get(joint["b"])
            if a is None or b is None:
                raise ValueError("mechanism references a removed body")
            if joint["type"]=="pivot":
                connection=pymunk.PivotJoint(a,b,joint["anchor"])
            elif joint["type"]=="motor":
                connection=pymunk.SimpleMotor(a,b,joint["rate"])
            else:
                connection=pymunk.DampedSpring(a,b,(0,0),(0,0),joint["length"],joint["stiffness"],joint["damping"])
            connection.max_force=joint["max_force"]
            self.space.add(connection)

    def _contact(self, arbiter, space, data):
        a, b = arbiter.shapes
        for actor, other in ((a, b), (b, a)):
            if actor not in self._shape_joints:
                continue
            name = self._shape_joints[actor]
            self.joint_contacts.add(name)
            if name.endswith("foot"):
                # Contact must support the foot from below, not be a side wall.
                p = self.ends[name][0].local_to_world(self.ends[name][1])
                if other.point_query((p.x, p.y + 5)).distance < 2:
                    self.ground_contacts.add(name)
            if other in self._shape_objects:
                self.contact_ids.add(self._shape_objects[other])

    def step(self, control):
        from .world import OFFSETS, DT
        w = self.world
        self.space.gravity = (0, w["gravity"])
        self.space.damping = clamp(w["material"]["damping"]**4,.5,.999)
        for body in self.space.bodies:
            if body.body_type==pymunk.Body.DYNAMIC:
                body.velocity=(body.velocity.x,body.velocity.y*w["material"]["vertical_damping"])
        drive = control.get("drive", 0)
        human = w.get("human", {})
        if human.get("until", 0) >= w["tick"]:
            drive = human.get("drive", drive)
        pose = {name: list(value) for name, value in OFFSETS.items()}
        phase = w["tick"] * DT * (5 + abs(drive) * 4)
        for side, offset in (("left", 0), ("right", math.pi)):
            swing = math.sin(phase + offset)
            pose[side + "_foot"][0] += swing * w["controller"]["stride"] * abs(drive)
            pose[side + "_foot"][1] -= max(0, swing) * 42 * abs(drive)
            pose[side + "_knee"][0] += swing * 14 * abs(drive)
            pose[side + "_hand"][0] -= swing * 10 * abs(drive)
        pose.update(control.get("pose", {}))
        strength = w["controller"]["balance"] * w["material"]["pose_strength"] / .08
        for name, spring in self.springs.items():
            body, length, a, b = self.segments[name]
            angle = math.atan2(pose[b][1] - pose[a][1], pose[b][0] - pose[a][0])
            angle += round((body.angle - angle) / (2 * math.pi)) * 2 * math.pi
            spring.rest_angle = -angle
            spring.stiffness = body.moment * (1800 if name == "hip" else 2800 if "knee" in name or "foot" in name else 500) * strength * w["material"]["stiffness"]
            spring.damping = body.moment * 90 * min(1, strength)
        torso = self.segments["hip"][0]
        total_mass = sum(b.mass for b in self.space.bodies if b.body_type == pymunk.Body.DYNAMIC and b not in self.objects.values())
        grounded = bool(self.ground_contacts) or any(p["y"] > 530 for key, p in w["nodes"].items() if key.endswith("foot"))
        desired = drive * w["controller"]["speed"]
        torso.apply_force_at_world_point((clamp((desired - torso.velocity.x) * total_mass * (35 if grounded else 1.5), -18000, 18000), 0), torso.position)
        if (control.get("jump") or human.get("jump")) and grounded:
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
        head.apply_force_at_world_point(force * strength, head.position)
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
            if (obj.position - point).length < 55:
                joint = pymunk.PivotJoint(body, obj, point)
                joint.max_force = 4500
                self.space.add(joint)
                self.grip = (target_id, joint)
        pointer = human.get("pointer")
        grabbed = self.objects.get(human.get("object"))
        if pointer and grabbed:
            f = (pymunk.Vec2d(*pointer) - grabbed.position) * 65 - grabbed.velocity * 9
            grabbed.apply_force_at_world_point((clamp(f.x, -8000, 8000), clamp(f.y, -8000, 8000)), grabbed.position)
        self.contact_ids.clear()
        self.ground_contacts.clear()
        self.joint_contacts.clear()
        for _ in range(2):
            self.space.step(DT / 2)
        for name, (body, local) in self.ends.items():
            p = body.local_to_world(local)
            velocity = body.velocity_at_world_point(p)
            w["nodes"][name].update(x=p.x, y=p.y, px=p.x - velocity.x * DT, py=p.y - velocity.y * DT)
        for obj in w["objects"]:
            if obj["id"] in self.objects:
                b = self.objects[obj["id"]]
                obj.update(x=b.position.x, y=b.position.y, vx=b.velocity.x, vy=b.velocity.y,
                           angle=b.angle, angular_velocity=b.angular_velocity)
        w["contacts"] = {"objects": sorted(self.contact_ids), "support": sorted(self.ground_contacts),
                         "joints": sorted(self.joint_contacts), "grip": self.grip[0] if self.grip else None}
        w["tick"] += 1
