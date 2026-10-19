# Physical film v10 — experimental checkpoint

The new “Физический мультфильм” creates a dedicated Matter / Dagi session.
It begins with a folded stick skeleton on white, not a loose pile of disconnected
rods. An authored controller unfolds it, balances, develops the procedural vector
world and face, then attempts a jump. Continuous landing is unstable and can end
with head contact. Such contact is labelled as failure on screen. This is not a
finished high-quality cartoon, learned walking or autonomous self-improvement.

## Physical changes

- Relative, equal-and-opposite joint PD torques are recomputed every solver
  substep. Mass, gravity, contacts and inertia determine motion. Initial placement
  is done only when creating the film; playback does not teleport the body.
- This film has stage_rig=false, no external support and no flight impulses.
  The legacy v9 stage-assisted example remains available separately.
- COM, velocity, angular momentum, energy, support margin, contact impulse and
  muscle effort are exposed to the controller and optional COM overlay.
- Slow motion reduces integrated dt; gravity and velocity units remain unchanged.
  Browser playback respects playback.speed. Offline advance defaults to physical
  time; pass time_scale=None to reproduce the cinematic timing.
- Joint muscle activation drives cosmetic surface volume within collider bounds.
  Face/hair, gradients, lighting, scenery and camera effects remain vector code.
- Browser vision contains the current world, a vector re-render of the same head,
  recent frames and physical measurements. It does not itself call the model.

## What is not solved

Landing passed one separately reconstructed candidate trial but failed the
continuous film from frame zero. It must not be advertised as a mastered skill.
The remaining controller is sensitive to its trajectory and solver state. No
further optimization was performed after the operator requested a status update.

This is a simplified 2D rigid capsule model with bounded internal actuators,
not validated human biomechanics. Film self-collision and activation lag are
turned off. Illustrative scale: 100 pixels per metre; energy divides pixel-based
values by 10000. COM/momentum cover the character, head and appendages, excluding
carried objects/mechanism bodies. Facial expression is a presentation channel.

## Editable source

`physical_film.py` installs the initial world; `examples/body-controller.js`
contains balance/jump feedback; `examples/matter.js` contains presentation and
slow-motion direction. `dynamics.py` measures the solver. Read these through the
source allowlist. Existing world-edit, project, fitness and memory tools remain
available. The new demonstration is authored; it is not a general autonomous
learning loop. Playback QA uses a provider that raises on any model call.

Run `uv sync --extra dev`, then `uv run dagi-web` with the existing configuration
and credentials described in README. Open `/game/` and use “Физический мультфильм”.
“Сначала” creates another film session. “Прыжок” requests a new attempt and may
fail. Source handoff only: no push, deployment or remote issue updates.
