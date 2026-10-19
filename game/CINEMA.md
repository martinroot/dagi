# Cinema v9 — an authored world, a reusable film instrument

The new **▷ Новый мультфильм** button creates a separate, explicitly scripted
38-second film. It does not replace another session. Playback, replay, material
passes, human attention and the stunt button run locally without model calls.
The ordinary **Чистая сессия** still starts with an unassisted skeleton and no
installed skill, choreography or learned gait.

The first short: establish → full figure → waist → face → wink → smile →
**Hello I'm Dagi** → three material reconstruction waves with a changing
landscape → detailed new portrait/hair → pull back → assisted physical flip →
landing → push toward a springy guard stance. The final pose continues locally.

`game/examples/hello-dagi.js` contains that authored example. All timings,
poses, palettes and camera keys are editable project source.
`game/examples/story-kit.js` is a small general CommonJS library: interpolate
numeric/vector/color tracks, easing functions and clip selection. Other
projects can copy and change it, or write entirely different JS. No activity
names, story beats or film sequence are built into the renderer or solver.

## Presentation channels

Projects can return `look`, `speech`, `camera` and `expression` together with
ordinary physical `control` and durable `state`. These channels use the same
60 Hz server timeline. A paused simulation freezes facial acting and the film.
The camera still supports ordinary viewer-side damping; `camera.cut:true`
samples an authored eased camera track exactly. Zoom now supports .65–10.
Reduced-motion preferences cap zoom and suppress shake/transform particles.

- `look.character` accepts cosmetic style/surface/features only. It cannot
  edit bones, collision radii, masses or add hidden body movement.
- `look.art` updates lighting and atmospheric presentation; static vector
  layer composition remains an authored world edit.
- `look.environment` changes vector scenery. Painted changes do not move the
  physical floor or add colliders.
- `look.reveal:{progress,band,color}` rebuilds the picture upward across the
  measured body with a scanning highlight and vector particles. A sequence
  of progress ramps provides repeating material transformations.
- `speech:{text,speaker,progress,opacity,color}` draws a vector dialogue bubble
  above the actual head. Text reveals by Unicode code point, wraps, and stays
  inside the shot; it has no HTML or external asset channel.
- `expression` adds independent `blink_left`, `blink_right`, `smile`, `brow`,
  `clench` channels, each 0–1. Existing gaze, mouth, surprise, tilt, valence and
  focus remain. Cues are authored expression, not subjective feelings.

Omitted look/speech/face channels reset instead of sticking to an old frame.
Per-frame cosmetic overrides do not mutate authored character geometry or
invalidate physical skill certificates. They remain bounded and validated.

## Vector portrait

`character.values.features` (or `look.character.features`) supports:

| Field | Values |
|---|---|
| hair | none, crop, swept, spiky, bob |
| hair_color, iris, brow, lips | #RRGGBB |
| hair_length, detail, freckles | 0–1 |
| eye_size | .7–1.3 |

The portrait has shaped eyelids, independent wink/blink, iris striations,
pupils/catchlights, curved brows, nose/lip planes, smile/teeth, ears and small
freckles. Hair is gradient-filled Bezier geometry with individual strands.
Hands can close into a decorative fist inside the capsule envelope. These are
presentation features, not additional independently simulated facial muscles,
hair strands or finger joints. The world remains procedural Canvas vectors,
including materials, landscape strata, vegetation and soil/stone marks. No
raster assets, image-generation service or picture download is involved.
Visual quality is a human judgement; “5× quality” is not a measured claim.

## Explicit physical stage rig

This film uses `body_control.values.stage_rig:true`, disabled by default.
`control.rig` sets a desired hip position and an unwrapped torso angle. Finite
PD forces and torques act on a **dynamic** torso through the existing Chipmunk
solver; limb muscles/relative servos, mass, gravity, inertia, contacts and joint
limits continue to operate. The rig never assigns body positions or velocities.
The example uses aid through launch, flight, recovery and the final pose; the
flip is a powered stage stunt, not an unassisted muscular skill or a purely
ballistic demonstration.

The UI labels the aid **СЦЕНА · СИЛОВАЯ СТРАХОВКА**, with separate positive stage
work. Releasing/omitting the rig command removes its support. `r.external_supports`
includes the enabled rig, so the v8 example's unsupported-walking guards reject
it. Changing stage configuration invalidates prior physical certificates.
Unwrapped angles survive solver reconstruction, so resume does not silently
turn a completed rotation into a new accidental spin.

The packaged film supplies its initial arrangement only at creation of a new
set. Replay changes the project time origin and rotation winding; it does not
reset the live body. The film's configured limb targets are anatomy-specific.
Changing physical proportions or adding obstacles requires a fresh physical
trial and visual review.

## Agent use

`game_observe view=schema,path=cinema` returns exact bounded contracts.
`view=source,path=game/examples/story-kit.js` and
`view=source,path=game/examples/hello-dagi.js` expose reusable example source,
with ordinary character-offset paging. `game_iteration` still tests and
publishes agent-written projects; named local project events can start a clip,
replay, respond to attention or select an entirely different sequence.
Creative quality needs human review. Use measurable timing/physics contracts
where appropriate, and do not manufacture a fitness score for beauty.

## Verification

371 Python tests and 52 Node UI tests passed. The full film, replay and mobile
layout were exercised in Chromium. The recorded run measured approximately
60 Hz physics and a 33.3 ms render-frame P95 during video capture. No browser
errors, mobile overflow, external images or model calls were observed. The
physical rollout checks a full rotation, real foot contacts, final posture,
bone lengths, aid accounting and solver reconstruction. This is evidence of
execution and contracts, not independent aesthetic certification.
