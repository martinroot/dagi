# Director v5 — agent-owned scene projects

The agent owns an executable JavaScript project for the creative part of its
world. A project coordinates physical behavior, camera, gaze, facial expression,
vector graphics and reactions in one program. A new session still starts with a
bare skeleton: there is no shipped story, prop layout or activity progression.

## Run and upgrade

```sh
uv sync --extra dev
uv run dagi-web
```

Use the existing `DAGI_API_KEY`, `DAGI_BASE_URL`, `DAGI_MODEL` and web account.
Open `/game/`. Create a session or open an existing one. Existing policies, scenes
and drafts are migrated additively. A service restart pauses local execution and
never authorizes new model spending; click **Продолжить занятие** to resume.
**Начать развитие** authorizes the explicitly selected number of model turns.

This version requires `python-quickjs-ng==0.12.1.1`, imported as `quickjs`. It is
installed by `uv sync`; no Node service is needed on the deployment server.

## Model workflow

The same three model tools remain: `game_observe`, `game_iteration`, `game_life`.
`game_observe {view:"schema",path:"project"}` gives the complete project contract.
A single iteration can edit up to 24 world/project items, test them offline, and
publish the passing configuration through the existing countdown. Optional local
parameter search also works on project params; up to eight physical alternatives
are evaluated without additional model calls.

```json
{
  "objective": "A concrete change chosen by the agent or requested by the human",
  "changes": [{
    "operation": "project",
    "name": "my-project",
    "description": "What this version actually implements",
    "files": {
      "main.js": "module.exports=({t,s,state})=>({state:{ticks:(state.ticks||0)+1},control:{drive:Math.max(-1,Math.min(1,(450-s.x)/100))},camera:{target:'head',zoom:1.6},expression:{focus:.8,gaze:[450,s.y-65]},beat:'approach'});"
    }
  }]
}
```

The example illustrates syntax only; it is not installed into clean sessions.
Each file uses CommonJS exports and project-local `require('./helper.js')`.
Functions, loops, classes, arrays and ordinary math work. File edits merge with a
saved project; `replace:true` replaces its complete file set. Projects have a
maximum of 12 files / 48,000 source characters, 24 numeric parameters, and 12
saved names. `game_observe {view:"code"}` returns a small project or a file index;
`path:"main.js",offset:0` reads a file in 5,000-character pages. Code and JSON
state are persisted with the session in SQLite.

## One program, synchronized channels

The entry exports a synchronous `function(input)`. Inputs are:

- `t`: seconds since project activation; publication rebases it to zero.
- `dt`: 1/60 second.
- `s`: live physical joints, position, velocity, bodies, goal and appendages.
  `s.contact_evidence` contains actual object/support/grip contacts;
  `s.contacts` retains the older per-joint geometric surface sensor.
- `s.runtime.thinking`: an actual running model/tool turn, including human turns.
- `state`: durable program memory; module variables are recreated each tick.
- `params`: saved numeric parameters.
- `event`: one queued human event or null.

The result can contain:

| Channel | Effect |
| --- | --- |
| `control` | Physical drive, jump, assisted joint poses, forces, grip and appendage angles |
| `camera` | Follow a joint, object, appendage or coordinate; zoom, offset, easing, shake and letterboxing |
| `expression` | Valence, arousal, focus, surprise, mouth, squint, head tilt and gaze |
| `draw` | Lines, circles, ellipses, paths, rectangles and text in world or screen coordinates |
| `hide_body` | Replace the default body drawing with authored graphics tied to physical sensor positions |
| `caption`, `beat` | Current readable activity and authored episode phase |
| `state` | JSON object up to 8 KB, retained between ticks and page reloads |

For deliberate choreography, use time and explicit state. For interaction
outcomes, use observed contact/position/error. A timed smile or a scripted
caption is presentation; neither proves understanding nor task success.

The browser interpolates positions and appendages from streamed physical frames.
Camera easing is presentation only. Pointer dragging and authored component
buttons invert the same camera transform, so controls remain usable when zoomed.
**Общий план** temporarily overrides the authored camera; reduced-motion settings
limit zoom and disable shake. Screen widgets remain fixed and accessible.

`appendage {part:{id,parent,length,angle,radius,mass,color}}` adds a real capsule,
pivot and assisted rotary motor to an existing skeleton joint or earlier
appendage. `control.appendage_pose` controls its absolute angle. The original
skeleton remains fixed and assisted; the system is not learned biomechanics.
`remove_appendage` removes a descendant chain. Bodies and mechanisms can also be
created, edited or removed in an iteration.

A widget or component can declare a target
`{type:"project",name:"my-project",event:"my-event"}`. It dispatches locally
without model calls. **Позвать агента** supplies `human_attention`; the project
chooses how to react. The viewer supplies no default reaction or storyline.

## Execution and evidence boundaries

JavaScript runs in QuickJS on the server, independently of browser/API latency.
Each invocation is limited to 8 ms CPU, 8 MB heap and 256 KB stack. The engine
exposes no Python callbacks, host filesystem, network, process or browser APIs.
This is an in-process embedded interpreter, not a separate OS security boundary.
Only validated data enters the physics and renderer. Project files do not
hot-patch host engine, authentication, billing or the core agent process.

New projects run a 12-second cloned physical trial before publication. Existing
policy trials stay at four seconds. These are sampled execution checks, not
proof for every future input or every authored phase. Invalid outputs and late
runtime errors disable the project, preserve source/error evidence and leave
idle physics alive. Failed candidate checks preserve the active world.

A passing trial records finite execution, posture and existing layout/component
checks. It does **not** certify interesting behavior, aesthetics, useful
self-reflection or improvement toward an arbitrary human goal. Visual quality
requires the real model to inspect actual images and respond to human feedback.

With browser vision enabled, the model receives up to three recent chronological
canvas panels, timestamped and version-bound, in one JPEG. No chat/desktop is
captured. Image detail is `auto`; the provider determines actual image token
usage. The context admission check reserves an estimate of 2,048 tokens; it is
not a billing guarantee. With no browser open, physics continues, but no fresh
image is fabricated or supplied. Disable vision for text-only providers.

Model/tool work remains visible in the existing activity animation and real
countdown. Local behavior, camera and reactions consume CPU, not model tokens.
Game provider turns are capped at `min(operator cap,12)` calls. This is per turn,
not an aggregate monetary limit for the entire autonomous sequence.

## Validation of this release

Automated tests cover JavaScript modules and persistent state, thread/session
separation, runaway interruption, invalid channels, actual appendage geometry,
delayed errors, version-bound human events, local controls and old snapshot
migration. Browser checks cover actual publication, camera transitions, physical
grip, server motion, human attention, pause/resume, reload and mobile overflow.

The integration film uses an explicitly **scripted test provider** returning a
known project. No external LLM API is called by that fixture. It verifies the
execution mechanism, not the ability of a live model to invent a good episode.
The deployment uses the owner's configured provider credentials; ChatGPT session
access is never forwarded into the application.
