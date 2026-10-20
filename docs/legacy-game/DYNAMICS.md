# Matter v11 — physical film preset

The “Физический мультфильм” button creates a dedicated Matter / Dagi session.
The actor starts as a folded stick skeleton on white, unfolds under internal
joint torques, develops its vector surfaces/world, shows face and hand details,
then performs a jump with slow motion and settles into foot support.

This is an authored demonstration, not a learned skill or an autonomous agent
training result. It is a reusable starting project for future internal debugging.
“Five times better” is an artistic target, not a measured quality certificate.

## What changed after v10

- Distinct upper-arm, forearm, thigh and shin silhouettes, muscle planes, narrow
  tendons, restrained skin marks and soft joint folds replace repeated capsules.
- Palms, four segmented fingers, thumbs, knuckle folds and nails are vector paths
  attached to the measured wrist. Fingers are cosmetic, not independent bodies.
- Smaller eyes, orbital shadows, tear ducts, layered skin/iris/hair details and
  smoother hair silhouettes improve close framing. Expressions follow the jump
  phase: preparation, effort, flight, landing, then a smile after stable support.
- Graphite shorts are optional cosmetics: surface.garment in 0..1 and fabric hex
  color. Defaults preserve ordinary characters; the film enables them.
- Smooth landscape ridges, haze and height-dependent foot shadows preserve the
  shared palette and vector construction. No image generation or raster assets.
- Film physics uses 8 substeps and 32 solver iterations. Relative servos refresh
  each substep. Takeoff parameters and landing feedback were revised; arms return
  during landing and ankle feedback follows actual velocity/COM displacement.
- Captured flight joint targets clamp small numerical limit overshoot instead
  of disabling the entire controller with an invalid target.
- Optional toe bone heel in 0..16 extends the actual capsule/moment, not only a
  drawing. Film heel remains 0: other heel geometries need controller retuning.

## Gates and evidence

The v10 continuous run failed. The v11 regression starts at frame zero and runs
through 32 physical seconds with cinematic dt. It checks no head/hand/non-foot
contact during the jump, a COM peak over 45 px above standing, final foot support
for at least 4.5 seconds, no external supports, and zero stage work. The preset
also exposes a success flag only after supported low-speed, low-rotation stance;
loss of balance is labelled even without head contact. This is a regression for
this body/initial world, not certification for arbitrary dimensions or terrain.

Playback QA prohibits model calls. Full suite: 379 Python and 52 Node UI tests;
intermediate browser frames and an uncut canvas recording are in the handoff.
The measured reference run lands, with 5.02 seconds final stable support, about
0.537 seconds free flight and about 30.32 px COM rise after takeoff. COM rise from
standing is larger because takeoff occurs after extension from the crouch.

## Physics boundary

Stage rig is off; no free flight impulse, global root motor or playback position
writes are used. Initial placement is only done when creating the film. Gravity,
contacts, inertia and bounded equal-and-opposite joint torques drive movement.
The legacy v9 stage-assisted film remains separate.

This remains a simplified 2D capsule/polygon model. Self-collision and activation
lag are disabled in this film. Cosmetic hands, face, garment and muscle shading
are not validated human biomechanics. Mass/COM/momentum cover the skeleton, head
and appendages, excluding carried objects/mechanism bodies. Scale is illustrative:
100 pixels per metre; energy divides pixel-based quantities by 10000.

Slow motion changes integrated dt, preserving gravity/velocity units. Offline
advance defaults to physical time; pass time_scale=None for cinematic playback.
Changing playback timing, proportions, masses, feet, ground or initial state
requires fresh full-rollout validation. Repeated manual jumps are experimental.

## Source and launch

The old physical film preset was removed. The generic solver remains for saved projects.
`examples/body-controller.js` provides internal feedback; `examples/matter.js`
provides timing, look, camera, expressions, material events and gates.
`dynamics.py` measures physics. Read these through the source allowlist.
The controller also exposes optional experimental air/landing parameters; the
recorded preset uses its frozen launch configuration and captured airborne pose.

Run `uv sync --extra dev`, then `uv run dagi-web` using the existing README
configuration/credentials. Open `/game/` → “Физический мультфильм”. “Сначала”
creates another film session; “Материалы” replays the material sweep locally.
Old saved film sessions retain their code: create a new film for v11.
No push, deployment or remote issue updates were performed.
