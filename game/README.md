# Dagi living lab

An optional visual environment around the existing Dagi model/tool loop. Every
new session starts with one bare stickman. There is no built-in activity planner,
level ladder, prop curriculum or complexity-score release gate. The model chooses
what to change. Its code controls the physical body between model turns.

## Run

Use your existing Dagi provider and web-account configuration:

```bash
uv sync --extra dev
uv run dagi-web
```

Open `/game/`, create a session, choose an iteration count and press **Начать
развитие**. A server clock advances physics in short deterministic 60 Hz batches.
The existing model/tool worker receives periodic development requests, up to the
selected 1–20 iterations. Each turn uses the operator-configured Dagi provider
call/money budget, including compression/delegation. The maximum aggregate call
count is iteration count × configured calls per run; money caps are per run,
not one global cap for the entire development session.

**Продолжить занятие** runs the selected saved controller without model calls.
Named policy buttons select and run a saved controller. **Пауза** freezes physical
time and cancels the currently owned autonomous model turn. Human chat remains
available between turns. A server restart preserves code and memory but pauses
worlds; it never automatically spends API budget or catches up elapsed time.
Closing a browser tab does not pause a running server world.

## General extension mechanism

The model gets a fresh passport before every provider call: identity, environment,
active feedback source/version, measured pose, latest physical errors, recent
release evidence and scoped experience. It knows that its brain is API requests
and its durable changes are code/configuration, not model weights. Perception is
structured geometry and physical sensors. No screenshot vision is supplied.

`game_design operation=inspect` returns exact schemas, current policy sources,
sensors, appearance, physical material and recent measured releases.

| Operation | Capability |
| --- | --- |
| `policy` | Author stateful conditional feedback code, evaluated every physical tick. |
| `appearance` | Change body stroke/fill/accent, thickness, head/joint display radius and motion trails. |
| `material` | Tune damping, friction, posture assist, constraint stiffness and solver iterations. |
| `body` | Create dynamic rectangular or circular objects with mass, restitution and two-way body contacts. |

A policy is a bounded Python **expression** returning a dictionary, interpreted by
an AST walker without `eval`, `exec`, attributes, imports, loops or host access.
Inputs are `s` (time, dt, position/velocity, posture/support, joints, contacts,
objects and configured goal) and `m` (persistent JSON memory). Output fields:

- `drive`: continuous -1..1 horizontal drive.
- `jump`: a boolean impulse when actually supported.
- `pose`: joint target offsets relative to the hip.
- `forces`: per-joint accelerations.
- `object_forces`: physical forces on authored dynamic objects.
- `memory`: next JSON state, preserved between ticks and page reloads.
- `intent`: short public activity displayed beside the stickman.

Arithmetic, indexing, dictionaries, conditions and bounded math functions support
feedback algorithms, oscillators and memory-based state transitions. The engine
contains no named activity semantics. Code is capped at 8000 characters/600 AST
nodes; memory is capped at 2048 characters. Editing/choosing a policy resets its
memory. Current controller source is available through `game_design inspect`.

The legacy short action programs and world objects remain compatible. Existing
`game_visual operation=component` also accepts agent-authored JavaScript drawing
and interaction programs. These execute in disposable browser workers within an
opaque sandbox frame. Real browser compilation/execution reports, watchdogs,
bounded output and declared events remain mandatory. The viewer must be open to
test these components. JavaScript visual code cannot modify the Python host.

## Measured change and release

```text
game_build begin objective=...
game_design policy / appearance / material / body
    or game_visual component / widget / theme
game_build test
game_inspect view=draft
game_build commit
```

A draft freezes live physics so evidence cannot silently become stale. Tests run
on clones from the same starting world. Every saved legacy behavior is executed,
even without a skill card. The active feedback source is exercised for 240 fixed
steps, including later inputs and memory transitions. Runtime errors block release.

Reports include baseline/candidate travel, displacement, upright/support ratios,
maximum bone-length error, sampled speed jitter and grounded foot slip. These
are diagnostics for an experiment, not an intelligence/aesthetic/usefulness score.
A simpler controller can pass. Unchanged source/configuration cannot be released.
Visual checks measure geometry and contrast, not subjective artistic quality.

Only the exact passing candidate can be activated. The human sees the real
SATISFY → 3 → 2 → 1 → БАХ release; the selected feedback code then continues with
the running world. Release history retains the objective and measured comparison.
Cancellation/crash cannot silently replay a pending release.

## Boundaries

This remains an assisted 2D Verlet skeleton, not a biomechanics or full rigid-body
engine. Dynamic round bodies use circle contacts; rectangular contacts use AABBs.
Dynamic objects have gravity, floor/wall contacts, mutual contacts and two-way
skeleton impulses. Arbitrary hinges, articulated machinery, bone-segment collision,
rotation and full stacking are not implemented. Head display radius changes are
cosmetic; the collision radius stays fixed. Physical material and feedback code
are editable; installed Python engine source is inspectable but not hot-patched.

An open-ended mechanism does not guarantee that a particular model will invent
interesting behavior or improve every iteration. Tests establish execution,
isolation, continuous motion, lifecycle and evidence. They do not certify
external-model learning, aesthetic quality or AGI.

## Verification

```bash
uv run python -m pytest -q
node --test tests/test_core_web_ui.js tests/test_game_ui.js tests/test_game_studio_ui.js tests/test_game_authored_ui.js
uv build
```

The live browser check uses a **scripted provider**, explicitly identified as such:
create a bare session, start a bounded development turn, publish/test feedback
code, observe continued motion with no further model calls, pause, resume, reload
and confirm an independent new session is empty. A live external-model evaluation
requires your configured provider and must be assessed separately.
