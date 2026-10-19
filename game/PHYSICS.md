# Physical Workshop v6

New browser sessions start with an unassisted articulated body, an empty physical
world and an editable sky/ground. There is no standing controller, walking gait,
root-body translation force or jump impulse. Existing sessions retain their
explicitly labelled assisted mode for compatibility.

```sh
uv sync --extra dev
uv run dagi-web
```

Create a **new clean session** at `/game/`. **Запустить физику** starts local
simulation without a model call. With no controller the body loses balance and
falls. **Начать развитие** authorizes the selected number of model turns to
write/test controllers or constructions. A falling trial is valid experimental
evidence, not a claim of successful locomotion.

## Body and control

The new skeleton has separate foot/ankle links, a pivoted head, joint limits and
11 internal rotational actuators. Non-adjacent body parts collide; adjacent
parts sharing a joint are filtered to avoid contradictory collision geometry.
No global angular springs hold physical limbs upright. Physical mode uses four
integration substeps per 60 Hz frame. Gravity for a new session is 981 pixels/s²,
with a nominal scale of 100 pixels/meter. Mass is in kilograms.

`control.muscles = {right_hand: .5}` applies a bounded torque to the elbow and
an equal opposite torque to its parent. Names refer to the child segment:

| Name | Joint |
| --- | --- |
| `left_elbow`, `right_elbow` | Shoulder |
| `left_hand`, `right_hand` | Elbow |
| `left_knee`, `right_knee` | Hip |
| `left_foot`, `right_foot` | Knee |
| `left_toe`, `right_toe` | Ankle |
| `head` | Neck |
| Appendage ID | Added articulated segment |

`control.servos = {right_hand:{angle:.8,stiffness:12000,damping:180,max_torque:15000}}`
is an explicitly requested **relative** PD joint controller. It applies bounded
internal torques; it is not a world-aligned posture or balance aid. The model can
write its own feedback directly with `muscles`, `s.articulation` angle/velocity,
contact evidence and durable project state. Getting up, balancing and walking
remain substantial controller-development tasks.

Physical mode rejects nonzero `drive`, `jump`, absolute `pose`, free skeletal or
object forces, and absolute appendage poses. Grip requires a body surface within
six pixels of the hand and has bounded holding force. Human dragging is an
external force. The manual joint panel/arrow keys apply muscle effort to one
selected joint; space releases effort. Holding a button does not run a walking
animation or a model call.

`body_control {values:{mode,muscle_scale,air_damping,joint_damping,self_collision}}`
is an explicit configuration edit. Choosing assisted mode restores labelled
legacy helpers. Assistance mode is included in trial results and the HUD; changing
it is not evidence of learned locomotion. Original world geometry/physics and
session memory are retained rather than silently reset.

## General construction

Read `game_observe {view:"schema",path:"physics"}` for exact current schemas,
or `view:"physics"` for authored materials, constraints and actual sensors.
The model edits these in the same atomic `game_iteration` as its JS project:

- Dynamic/static circles, rectangles and ordered convex polygons.
- Named materials with density, friction, restitution and colour. Density plus
  area and depth computes a body's mass unless the author supplies mass.
  Wood/steel/stone/rubber defaults are illustrative, editable coefficients.
- Pivot, distance pin, distance slide, linear spring, motor, gear, rotary limit,
  rotary spring and weld constraints.
- Endpoints on any body, `world`, skeleton joints such as `self:right_hand`, or
  added appendages. Local attachment offsets and world pivot coordinates are
  explicit.
- Colliding ropes built from massive capsule links and pivot constraints. They
  can route around a wheel, attach to a hand/load, go slack, transfer load and
  break. There is no hidden direct connection bypassing the pulley geometry.
- Removable bodies/constraints/ropes. Removing a body also removes dependent
  ropes and constraints.

`control.joint_controls` controls authored mechanism motors within their declared
torque limits. Rotational motor limits use simulation torque units; linear
constraint limits use simulation force units. Constraint impulses accumulated
across all substeps yield approximate reported loads. Physical motor work and
positive muscle work are reported separately; the nominal scale converts work to
joules and linear rope tension to newtons. Collision impulses and constraint
stabilization introduce numerical error; these are useful diagnostics, not a
calibrated engineering analysis.

Ropes use a discretized 2D chain, not continuum cable mechanics or 3D wrap
simulation. A new chain's endpoints follow its current attachment points; route
points specify its intervening initial geometry. The rope does not collide with
its own attached endpoint bodies, avoiding contradictory centre attachments.
Geometry and broken state survive checkpoints/rebuilds when the definition is
unchanged. The solver has no continuous collision detection and fast, very light
chains or extreme mass ratios can require gentler motors, shorter integration
steps or different link mass/spacing. Construction budgets are bounded: 64 bodies,
96 constraints, six ropes / 192 authored links, 12 appendages, 20 named materials.

No cars, robots, pulleys or walking programs are installed into a new session.
Those are constructions made from the same general bodies, joints and project
code. A fixed world joint or powered motor is an explicit source of support or
power; it must not be described as unsupported muscle learning.

## Hypotheses and measured checks

Trials return actual object displacement, rotation, position extrema, rope
breakage/peak load, work and body posture/contact fractions. The optional
`verify` field evaluates up to six author-specified predicates over candidate
metrics `r`:

```json
{
  "verify": [
    {"label":"The load rises", "expression":"r['objects']['load']['dy'] < -20"},
    {"label":"The rope stays intact", "expression":"not r['ropes']['line']['broken']"}
  ]
}
```

Supported object fields are `dx`, `dy`, `end_x`, `end_y`, `min_x`, `max_x`,
`min_y`, `max_y`, `rotation`; rope fields are `broken`, `length`, `peak_tension`.
`muscle_work`, `motor_work`, `upright_ratio`, `grounded_ratio` and existing trial
metrics are also available. Local numeric parameter search uses the same metrics.
A failed predicate preserves the current world. The source, tested parameters and
passing evidence are bound to the published candidate.

Predicates are selected by the author: a trivial check can pass, and a fixed
12-second project rollout cannot establish behavior for every future condition.
A passing test is not independent proof of mastery, usefulness or intelligence.
The model must state what motion it expects, inspect measured outcomes and actual
browser observations, and revise its mechanism/controller when evidence fails.

## Scene and skill interface

`environment {values:...}` edits sky/ground gradients, sunlight, cloud placement
and mountain silhouettes. These are presentation; collision terrain must be built
from static physical bodies. JS projects retain control of camera, expression,
world/screen vector graphics, captions and full custom body drawing. The physical
floor remains y=540 in the 1000×600 world. The scene is 2D.

Skill widgets accept an icon (`muscle`, `rope`, `wheel`, `hand`, `spark`, emoji or
text) and optional number hotkey. Common pictograms use bundled SVG paths, so
installed emoji fonts are not required. The persistent game hotbar dispatches
project events locally. A skill button is an ability binding, not a certificate
that its title has been mastered. Arbitrary names/icons/events remain authorable.

The completed human turn is cleared from local life state, preventing replay as
a spurious autonomous `0/0` iteration. This does not add model calls. All paid
turns still use the owner's configured provider and existing per-turn limits.

## Validation boundaries

Tests exercise unassisted collapse and zero work, equal/opposite muscle torque,
relative servo limits, actual material coefficients, hanging/breaking ropes,
hand attachment, a two-weight pulley, a wheel/chassis assembly, gear coupling,
local skill/muscle input, and failed mechanical predicate rollback. Existing
assisted behavior tests explicitly request the compatibility mode.

The recorded construction demo uses an explicitly **scripted provider**, not an
external LLM. Its torso is visibly and explicitly constrained to the world as a
hand/pulley test bench. Its movement is not learned walking. A separate empty
session recording shows uncontrolled collapse without assistance or model calls.
These tests establish mechanics and execution; live-model invention, sustained
learning and visual judgement require evaluation on the deployment provider.
