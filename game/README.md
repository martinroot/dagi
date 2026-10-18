# Dagi embodied debugging lab

The stickman is the acting agent's body in one session. This optional mode gives
the existing model/tool loop an observable physical environment for debugging
identity, actions, feedback, goal checks and iterative behavior changes.

## Start

Use the repository's existing Python/provider configuration and web credentials:

```bash
uv sync --extra dev
uv run dagi-web
```

Open `http://127.0.0.1:8765/game/` and sign in with the same Dagi Sandbox account.
The main inspector has an **Embodied lab** link. Reverse-proxy mounts such as
`/dagi/game/` work when the existing proxy forwards `/dagi/api/` to `/api/` and
the cookie path/public origin are configured for that mount.

Select **Чистая сессия**. It creates a fresh body, no objects, no goal, no custom
behavior and a distinct `game/sessions/<uuid>` workspace below `DAGI_WORKSPACE`.
Reopening a saved session resumes its saved world; it does not rerun actions.
Ordinary terminal/web sessions are unchanged and do not get game tools. Use the
web entry point for embodied runs; the terminal CLI is not a game viewer.

Start with **Осмотреть себя**, then **Дойти до цели**. The four preset buttons
fill the message composer; the human can edit and send the goal.

Example progression:

1. Identify the body, session, workspace, engine, behavior code and human viewer.
2. Remain upright, move toward a target and compare measured displacement.
3. Add a small block ahead of the body and test contact/jumping.
4. Change one controller parameter, run a comparable action and inspect effects.
5. Save a named action program, test it and record a short correction note.

The model may perform multiple experiments within one existing Dagi tool loop.
The normal provider-call, context, cost, cancellation and tool-round bounds still
apply. There is no background unlimited self-improvement process.

## Runtime identity and observation

Game runs get a separate application-owned system prompt alongside the existing
runtime context. A fresh `DAGI_SELF_PASSPORT_JSON` is injected before every model
request, including the first: identity, code map, LLM/JSON decision mechanism,
current world/build state, selected experience and release-check evidence. It describes the actual interface and asks for concise public
intent, observation and correction notes, not private reasoning transcripts.

`game_inspect` returns:

- The current `session_id`, `stickman:<session_id>` body identity and workspace.
- A code map: engine, adapter, agent loop, viewer and editable controller/programs.
- Joint coordinates, physical clock, posture, support, last action and goal check.
- The fact that a human sees the browser canvas, streamed chat and tool evidence.
- An explicit perception boundary: structured scene observations; no screenshot
  or pixel-level vision input is being supplied to the model.

Source inspection reads the installed allowlisted Python/JS/HTML files, with
bounded paging. It does not provide arbitrary host-file access. Detailed objects
and behavior programs are paged separately; ordinary movement feedback stays
compact. File tools operate inside the owning session workspace. Memory search
in a game run is restricted to that session; saved skills retain Dagi's existing
shared-skill semantics.

## Tools

| Tool | Effect |
| --- | --- |
| `game_inspect` | Read identity/current pose; `view=source`, `objects`, or `behaviors` for details. Use returned `next_offset` for paging. |
| `game_act` | Move left/right, idle, jump or climb up/down near a ladder for 1–240 fixed steps; run a named behavior. Returns actual displacement and pose/check state. |
| `game_evolve` | Add/remove blocks, markers, ladders or force-producing fans; change movement/posture/physics parameters; save a bounded behavior program. |
| `game_goal` | Configure a reach-x check requiring tolerance, upright posture and actual foot support. |
| `game_reflect` | Save expected result, a hypothesis and next test. The runtime attaches measured state and evidence revision/tick. |
| `game_visual` | Create/update panels, skill cards, todo lists, human buttons and theme colors. |
| `game_build` | Begin, batch-edit, test, commit or discard a self-improvement draft. |
| `game_review` | Report layout, content sizing, body occlusion, color contrast and current browser measurements. |

Example arguments:

```json
{"operation":"add","object":{"id":"step-1","kind":"block","x":400,"y":516,"width":60,"height":24,"label":"First obstacle"}}
```

```json
{"operation":"controller","values":{"speed":110,"balance":0.9,"stride":14}}
```

```json
{"operation":"behavior","name":"approach-and-jump","steps":[{"action":"right","frames":90},{"action":"jump","frames":30},{"action":"right","frames":60}]}
```

```json
{"action":"behavior","name":"approach-and-jump"}
```

Controller ranges: speed 0–180, balance 0–1, stride 0–24, jump impulse 0–450.
Gravity: 100–1600. A world has at most 32 objects and 12 named behaviors.
Programs contain 1–8 non-nested actions and at most 960 steps (16 simulated
seconds). Invalid edits and interrupted simulations roll back atomically.

## Physics and evidence

- Server-owned 60 Hz fixed-step Verlet integration, distance-constrained joints,
  gravity, world bounds and joint/AABB obstacle contacts.
- Eleven joints form the bare stickman. An explicit assisted posture controller
  balances it and supplies walking targets/velocity. With balance disabled, the
  same constrained body can collapse under gravity.
- This is a small physical debugging model, not a biomechanics engine: bones
  have no segment collision, obstacles are static, friction/contact geometry are
  approximate, and the posture assist is not a muscle/torque simulation.
- Physics time advances **only** through `game_act`. Viewer polling, model
  latency and reconnecting cannot change the world. Waiting alone does not
  cause a fall; an idle action is a simulated wait.
- The viewer interpolates saved server joint frames. It plays the most recent
  available action; several very fast actions may be coalesced between polls.
  The durable Dagi tool trace still records each call and outcome.
- A successful edit verifies the configuration was saved. A goal check verifies
  only the configured pose. Neither establishes the full natural-language task.
  Changing the target does not establish the previous target was reached.
- Reflection fields supplied by the model remain hypotheses. The observed pose
  and evidence revision/tick are attached by the runtime. No automatic promotion
  to a verified lesson is performed by this mode.

The agent can change its live *declarative* behavior code (controller plus named
action programs) and world through tools. It can inspect the real engine source
and write proposed extensions in its workspace. Proposals that modify Python or the installed viewer itself are not
automatically imported or executed by the service. Authored visual components
use a separate hot-loaded JavaScript worker protocol described below. Extending the engine
itself follows the normal code-review/test/restart workflow.

## Persistence and API

`GameStore` owns one additive `game_worlds` table in the existing Dagi SQLite
database. Each row belongs to one session. A `BEGIN IMMEDIATE` transaction
serializes each bounded mutation; partial ticks cannot leak on failure.
Snapshots keep the last 40 world changes, 20 operational notes and bounded
frames for the latest action. This is a current-state/debugging view, not an
unbounded world event-reconstruction system. The existing Dagi run/tool events
remain the durable execution record with session/run/tool-call identities.

World-changing tools are deliberately non-retryable and have no effect verifier.
If a process dies after a world commit but before Dagi stores the tool result,
the existing uncertain-outcome recovery policy applies; the action is not
blindly replayed. Inspect the world before deciding what to do next.

| Route | Result |
| --- | --- |
| `GET /game/` | Standalone lab page. |
| `GET /api/game/sessions` | Saved game sessions only. |
| `POST /api/game/sessions` | New clean game session; optional `title`. |
| `GET /api/game/sessions/<id>` | Identity, current scene, joints, latest motion, change history and notes. |
| `POST /api/sessions/<id>/runs` | Existing streamed chat/agent worker, now with game tools for game sessions. |
| `GET /api/runs/<id>/events` | Existing persisted/reconnectable SSE events. |
| `POST /api/runs/<id>/cancel` | Existing cancellation. |

Game APIs use the existing authentication and state-changing-request origin
checks. They do not expose the provider key. There is no raw world-mutation HTTP
endpoint; changes go through the existing agent tool execution path. This is
still the existing service user's process, not an operating-system sandbox.

## Verification

```bash
uv run python -m pytest -q tests/test_game.py tests/test_game_studio.py tests/test_game_authored.py
node --test tests/test_game_ui.js tests/test_game_studio_ui.js tests/test_game_authored_ui.js
```

The tests cover physical motion/fall/jump/contact, deterministic goal evidence,
behavior execution, invalid/cancelled mutation rollback, concurrent writers,
source allowlists, session isolation, actual web-to-agent-to-tool integration,
fresh/resumed worlds, stale UI responses and stream recovery.

Full repository gate:

```bash
uv run python -m pytest -q
node --test tests/test_core_web_ui.js tests/test_game_ui.js tests/test_game_studio_ui.js
uv build
```

The integration provider is scripted. These tests establish wiring and physical
effects, not an assessment of an external model's self-identification or
long-horizon learning. A live provider smoke experiment still needs an
operator-configured API key and a selected model.


## Studio v2: construct, test, satisfy, release

The **Улучши себя** button starts a normal bounded Dagi chat run with an explicit
self-improvement request. The model chooses and constructs a candidate, evaluates
it, repairs failed checks and publishes it through the same durable tool loop.
It is not a hard-coded scene generator; the fixtures in tests use a scripted
provider to verify this protocol. A live model remains responsible for choosing
useful changes within its configured tool/context/budget bounds.

```
game_build {operation: begin, objective: ...}
game_build {operation: edit, changes: [...]}
game_review {}
game_build {operation: test}
game_build {operation: commit}
```

Use `game_inspect {view: catalog}` for concrete component schemas and examples;
`view: draft` exposes the candidate and its test report. A draft supports at most
24 edits in batches of 1–8, and three physical test attempts. Edits through
`game_visual` or `game_evolve` target an open draft automatically. Live movement
and goal changes are blocked while a draft is open, preventing stale test evidence.
Discard a draft before continuing unrelated live experiments.

Available visual components:

| Component | Meaning and interaction |
| --- | --- |
| `panel` | Named information/communication surface with bounded text. |
| `skill` | Visual binding to an actual game tool or saved physical program; availability and test evidence remain distinct. |
| `todo` | Up to eight identified tasks with explicit done flags. |
| `button` | A human control bound to an allowed action, behavior, game tool or bounded user prompt. |

Widgets have stable IDs, world coordinates, dimensions and plain text. Widget fields accept no raw HTML. Authored JavaScript uses the isolated
component protocol described below; dynamic host-code execution is not provided. Human
buttons and todo clicks start a real chat run with the saved control's target;
execution uses the registry and existing run/tool persistence. They are not
zero-cost direct motor calls. Controls are disabled during active runs/drafts;
server-side run exclusivity and world-version validation also apply.

A ladder enables an assisted climb motor only when the body is near its actual
geometry. A fan applies an angle/range/strength-dependent force to joints during
fixed physical steps. Animation alone never supplies physical displacement.

The draft test clones the world and compares a 90-step physical-health probe
against the unchanged baseline. Checks cover finite physics, preserved goal,
posture regression, widget geometry/content bounds, body occlusion and contrast.
Behavior-bound skill cards also execute their saved programs on clones and
report measured movement/health, with an explicit limit on what that proves.
Tests never move the live body. Changes after a test invalidate its evidence.

Commit schedules a persisted 3.2-second countdown, waits outside the SQLite
write transaction, checks cancellation and the exact tested candidate, then
atomically swaps the live world. The human sees **SATISFY → 3 → 2 → 1 → БАХ →
WORLD vN**. The burst appears only after confirmed server activation. A missed
activation deadline shows a waiting state; it never fabricates a reload. Previous
live state is retained as one checkpoint. The page/chat session stays connected.

Cancellation during countdown keeps the live world unchanged. A process crash
before activation leaves the draft inspectable; startup recovery marks the
interrupted release for explicit retry rather than automatically replaying it.
Saved v1 worlds are migrated additively without resetting their body or history.

The orbit/workbench next to the stickman represents persisted provider/tool/run
state. It identifies the configured/active model and real API calls. It is a
public execution indicator, not a visualization of hidden reasoning. World time
still advances only through physical actions.

Visual review uses scene geometry, declared text sizing and luminance contrast.
The browser additionally reports actual component overflow and viewport sizes,
bound to the current scene hash. Reports are labeled untrusted browser telemetry;
stale reports do not count toward current review. Current overflow reports can
fail the readability check. No screenshot pixels are sent to the LLM, so this
mode does not claim to perform aesthetic vision judgments.

Additional authenticated routes:

- `POST /api/game/sessions/<id>/interact`: validate a current-world component and
  start the ordinary agent run for that click.
- `POST /api/game/sessions/<id>/render-report`: bounded, scene-hash-bound browser
  measurements. This updates telemetry only, not the physical world.


## Agent-authored components: extend the world with code

Examples such as a fan, ladder or todo are illustrative. The primary extension
mechanism is **code written by the acting agent**, not a fixed item catalogue.
The agent can invent an instrument, visualization or interaction that has no
predefined type in the engine, implement it, observe execution errors, repair it
and publish the exact tested source with the normal release animation.

Use `game_visual` with `operation=component` and a component object:

```json
{
  "id": "my-instrument",
  "title": "An instrument I invented",
  "x": 350, "y": 65, "width": 300, "height": 180,
  "layer": "foreground",
  "events": [{"id":"refresh","label":"Refresh"}],
  "code": "const n=(input.state.n||0)+(input.event?1:0); return {commands:[{type:'text',x:10,y:25,text:'Experiments: '+n},{type:'button',x:10,y:50,width:180,height:32,text:'Refresh',event_id:'refresh'}],state:{n}};"
}
```

`code` is an actual JavaScript function body. It receives `input` with `width`,
`height`, `time`, `dt`, transient `state`, structured `scene` and optional `event`.
It returns `{commands:[...], state:{...}}`. The function can define algorithms,
loops, computed geometry, animation and state transitions; the host does not
contain its named behavior. Drawing primitives are rect, circle, line, text and
button. All drawing is clipped to the component's declared bounds. Background
components render behind the physical body; foreground components render above.
Named events may be local to the program or have a declared registry/prompt
target for a real Dagi agent run. Physical effects and server tools still use
the existing tool/API contract rather than browser code modifying server state.

Up to eight components, each with 12,000 source characters and eight declared
events, are supported. `game_inspect view=components` lists their identities and
source hashes; `view=component_source,path=<component-id>` pages the actual saved
code, including a current draft. The automatically loaded passport identifies
these authored tools. Transient animation state resets on page reload/release;
source and declared behavior remain durable.

The browser compiles and runs each program in its own disposable worker inside
an opaque `sandbox=allow-scripts` iframe. Its CSP blocks network connections and
external scripts. DOM/network/nested-worker/postMessage capabilities are removed
from the authored worker globals. A host watchdog terminates slow compilation
or frame execution. Only bounded, validated draw output and declared events
cross back to the viewer. This is a browser execution boundary, not an OS or
hard memory-quota sandbox. It does not execute the agent's code in the Python
service or grant host credentials.

The browser reports real compilation/runtime errors and source hashes. A draft
containing code requires a current matching execution report before release.
An unopened browser leaves execution **pending**, not passed. Changed code
invalidates previous evidence. A test proves compilation, bounded execution and
validated rendering for the observed input; it does not prove every future
frame or all natural-language requirements. The runtime watchdog/validation
continues after publication.

The default **Улучши себя** request asks the agent to choose and implement a useful
extension. It does not prescribe a fixed collection of cards or physical props.
