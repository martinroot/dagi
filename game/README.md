# Dagi Genesis — living agent lab

A bare stickman, an open physical world and the normal Dagi model/tool brain.
The runtime supplies general mechanisms; the model chooses what to build and do.

```bash
uv sync --extra dev
uv run dagi-web
```

Keep the existing provider and web-account configuration. Open `/game/` and create
a clean session. Use chat for a requested change, or **Начать развитие** for a
bounded sequence of self-directed model turns. A passing `game_iteration` starts
its selected controller locally, without requiring another human click.

**Продолжить занятие** runs saved code without model calls. **Пауза** stops the
clock and cancels the owned autonomous turn. Running worlds continue when their
browser tab is closed. Restarting the service pauses worlds and preserves their
code/data; it never automatically resumes API spending.

The model receives three compact tools: observe, submit/test/publish an iteration,
and play/pause. Feedback code can act on pose, contacts, objects, memory and named
parameters. Rigid bodies rotate and exchange impulses. Generic pivots, springs,
motors and physical grips support invented interactions. Appearance, expressive
face/gaze and isolated JavaScript visual instruments are editable too.

The **Кадр мира для модели** option supplies an actual small canvas image to a
vision-capable provider. Disable it if the selected provider rejects images.
Drag physical objects or use arrows/space to perturb the world without tokens.

A physical clock, streamed snapshots and an independent browser render loop
replace per-action SQLite motor polling. Live behavior continues while candidate
changes are tested. Current-turn context replaces repeated historical snapshots;
each game turn is capped at min(configured provider cap, 8) calls. Autonomous
iteration count remains explicit; local motor execution does not add paid turns.

See [GENESIS.md](GENESIS.md) for architecture, precise boundaries and validation.
The engine is an assisted 2D physical character, not a learned human motor system.
A test passing establishes execution/safety checks, not guaranteed creativity,
aesthetic quality or improvement at every iteration.

```bash
uv run python -m pytest -q
node --test tests/test_core_web_ui.js tests/test_game_ui.js tests/test_game_studio_ui.js tests/test_game_authored_ui.js
uv build
```
