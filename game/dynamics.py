"""Measured mass, momentum, support and muscle evidence from the live solver.

Coordinates: pixels, kilograms, seconds. 100 pixels = one illustrative metre.
No metrics apply forces or stabilize the body.
"""
from __future__ import annotations
import math


def measure(sim,dt):
    import pymunk
    bodies=[v[0] for v in sim.segments.values()]+[sim.ends['head'][0]]+[v[0] for v in sim.appendages.values()]
    mass=sum(b.mass for b in bodies)
    com=sum((b.position*b.mass for b in bodies),pymunk.Vec2d(0,0))/mass
    velocity=sum((b.velocity*b.mass for b in bodies),pymunk.Vec2d(0,0))/mass
    momentum=sum((b.mass*(b.position-com).cross(b.velocity-velocity)+b.moment*b.angular_velocity for b in bodies))
    support=sim.support_points
    extent=[min(support),max(support)] if support else None
    margin=min(com.x-extent[0],extent[1]-com.x) if extent else None
    kinetic=sum(.5*b.mass*b.velocity.length_squared+.5*b.moment*b.angular_velocity**2 for b in bodies)/10000
    potential=sum(b.mass*sim.world['gravity']*(540-b.position.y) for b in bodies)/10000
    sim.world['dynamics']={
        'torso':{'angle':sim.segments['hip'][0].angle,'velocity':sim.segments['hip'][0].angular_velocity},'mass':mass,'com':[com.x,com.y],'velocity':[velocity.x,velocity.y],
        'linear_momentum':[mass*velocity.x,mass*velocity.y],
        'angular_momentum':momentum,'kinetic':kinetic,'potential':potential,
        'support':extent,'support_margin':margin,'contact_impulse':sim.contact_impulse,
        'ground_force':sim.contact_impulse/dt,'airborne':not sim.external_contact,
        'contacts':sorted(sim.external_contact),'solver_dt':dt,'substeps':sim.substeps,
        'stage_rig':sim.world['body_control'].get('stage_rig',False),
    }
