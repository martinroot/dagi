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
runtime context. It describes the actual interface and asks for concise public
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
| `game_act` | Move left/right, idle or jump for 1–240 fixed steps; run a named behavior. Returns actual displacement and pose/check state. |
| `game_evolve` | Add/remove blocks or markers; change movement/posture/physics parameters; save a bounded behavior program. |
| `game_goal` | Configure a reach-x check requiring tolerance, upright posture and actual foot support. |
| `game_reflect` | Save expected result, a hypothesis and next test. The runtime attaches measured state and evidence revision/tick. |

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
and write proposed extensions in its workspace. Python/JS proposals are not
automatically imported or executed by the live service. Extending the engine
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
uv run python -m pytest -q tests/test_game.py
node --test tests/test_game_ui.js
```

The tests cover physical motion/fall/jump/contact, deterministic goal evidence,
behavior execution, invalid/cancelled mutation rollback, concurrent writers,
source allowlists, session isolation, actual web-to-agent-to-tool integration,
fresh/resumed worlds, stale UI responses and stream recovery.

Full repository gate:

```bash
uv run python -m pytest -q
node --test tests/test_core_web_ui.js tests/test_game_ui.js
uv build
```

The integration provider is scripted. These tests establish wiring and physical
effects, not an assessment of an external model's self-identification or
long-horizon learning. A live provider smoke experiment still needs an
operator-configured API key and a selected model.
