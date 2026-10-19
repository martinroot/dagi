# Genesis runtime (game v4)

Base: martinroot/dagi main `69ce1e3`. This replaces the bottlenecks observed in
session 23; it does not ship predefined agent activities.

## Separation of clocks

- A dedicated server thread advances an authoritative in-memory Chipmunk world
  at a target 60 Hz with two substeps. It does not serialize JSON, open SQLite or
  invoke a model on a physics tick.
- `/api/game/sessions/<id>/frames` streams compact state via SSE at up to 30 Hz.
  The browser interpolates this stream and draws at its own animation cadence.
  Metadata polling is 1.5 seconds rather than a full-world motor clock.
- Semantic mutations are durable before visibility; live motion checkpoints every
  two seconds and on orderly shutdown. A hard crash can lose up to roughly two
  seconds of motion/motor memory. It never automatically resumes paid API turns.
- Off-line candidate tests use an unchanged seed. The existing body keeps moving
  during tests/drafts. Configuration hashes, not drifting joint positions, guard
  releases. Publishing retains current live pose/time and unchanged object state.

## Physics

Pymunk 7.2 / Chipmunk supplies rigid capsule limbs, pivot constraints, rotary
posture motors, whole-limb collision, friction, rotation, stacking, mass and
impulse exchange. The skeleton remains assisted: drive and pose use physical
motors, not a learned biomechanical locomotion model. Pose targets never directly
teleport joints. Legacy Verlet is retained for pure legacy snapshots/tests; web
worlds migrate to Chipmunk without deleting their authored programs.

General design primitives include circles, rectangles, pivots, springs and motors.
A policy can drive individual joint forces, object forces, pose targets and a
bounded physical hand grip. Runtime contact observations identify touched objects,
supporting feet and the actual active grip. These distinguish contact from merely
moving a nearby object by force.

## Small iteration protocol

The model sees three main tools:

1. `game_observe`: compact state, exact schema, active source, draft or source map.
2. `game_iteration`: one coherent edit package, real tests and tested publication.
3. `game_life`: execute or pause locally, or discard an old interrupted draft.

Older tools remain in the execution registry for compatibility, but their schemas
are omitted from new game model requests. Current-turn context is rebuilt from
complete tool exchanges plus the latest human direction and a compact passport.
Old unmatched pairs cannot poison a new turn. No compression model is called by
this game context builder. Full historical messages/outcomes remain in SQLite.
Each game turn is capped at min(operator cap, 8) provider calls. The user still
chooses a finite number of autonomous turns. Playing a motor alone never grants
additional model turns.

`game_iteration` accepts `objective`, `changes` (1..8), optional `play` (default
true), and optional local `search`. Changes use the existing design/visual edit
schemas, plus `joint`. One search compares up to eight numeric values for a named
policy parameter. Code accesses parameters through `p`; the score is a bounded
expression over measured trial metrics `r`, with higher preferred. These trials
use no extra model calls. A local score is experiment-specific evidence, not a
universal ability or intelligence score.

Failed candidates leave the current world intact. A late live policy failure
preserves its source, disables that controller and continues physical settling
so the entire renderer/world does not freeze. The next authorized model turn sees
the error and failed policy name. New abilities can be saved under separate names
and replayed via human controls without starting an LLM turn.

## Visual feedback and presentation

The canvas scales with device pixel ratio. Rendering includes cached lighting,
contact/altitude shadows, object orientation, shaded primitives, expressive eyes,
brows, mouth, gaze, blinks and release feedback. Expressions are interface cues,
not claims of subjective feelings. Policies output optional
`emotion:{valence,arousal,focus}` and `gaze:[x,y]`.

With **Кадр мира для модели** enabled, the browser uploads a 512×307 JPEG canvas
observation. Only a fresh frame for the current world version is eligible for the
model request, at low detail. The frame is supplied as actual image input, not a
textual claim that the agent can see. It contains the world canvas, not chat, DOM
cards or the host desktop. Older frames are excluded. Disable this option for a
model/provider that rejects images. Image token accounting remains provider-
dependent; the context admission estimate reserves 768 tokens per frame.

Arrow keys and space apply direct physical input. Dynamic objects can be dragged
with a mouse/pointer using a bounded physical force. These operations make no
model calls. Controls and observer inputs are scoped to the authenticated session.

## Validation limits

A real Chromium check uses an explicitly scripted provider to test the protocol,
not to claim open-ended model learning. Its initial measurements were about 60
physics steps/s, 29 streamed snapshots/s and up to about 60 rendered frames/s after background caching in a headless
software-rendered browser at 2× DPI. These are local observations, not universal
performance guarantees. A tested edit/publish operation required two provider
calls. A current canvas image was present in the captured request.

Live-model inventiveness, aesthetic judgment and improvement rate were not
measured: no user provider key was available in this environment. The engine has
no built-in "interesting activity" generator. Continuous local behavior depends
on authored controller code; selecting better experiments remains the model's job.

## Release verification

The final full gate passed 260 Python tests and 35 JavaScript UI tests. A real
Chromium check passed desktop/mobile layouts, actual image attachment, a tested
atomic publication, local continuing motion, pause/resume, persistence after page
reload and absence of browser page errors or horizontal overflow. A 4.5-second
canvas recording is included in the handoff under verification, explicitly
labelled as a scripted-provider fixture. It demonstrates mechanics, not model
inventiveness. After the final release-countdown transport adjustment, the
relevant UI tests and browser check were repeated.
