Current visual authoring: [Vector Character Studio (v7)](VISUAL.md) — anatomy, real proportions, muscle surfaces, vector layers and shared lighting.

# Dagi Physical Workshop

A bare physical stickman, editable scene and general mechanism construction.
New sessions have unassisted muscles and joint limits. Standing and walking are
controller-development tasks; there is no installed gait or balance routine.

```sh
uv sync --extra dev
uv run dagi-web
```

Open `/game/` and create a **new clean session**. **Запустить физику** runs the
uncontrolled body locally. **Начать развитие** authorizes the selected number of
model turns. The agent can write JS feedback projects, add bodies/materials,
connect joints and colliding ropes, test mechanical predictions, and publish a
passing candidate. Local execution runs without model calls or an open browser.

The skill hotbar supports icons, local events and number keys. The joint panel
applies manual muscle effort. The model can edit sky, ground, camera, expression
and graphics; physical terrain is made from static collision geometry.

Existing sessions keep their labelled assisted mode. Provider/account settings
are unchanged. Enable browser vision for chronological canvas observations and
disable it for text-only providers. A service restart preserves code/state and
pauses execution; it never authorizes new API spending.

Read [PHYSICS.md](PHYSICS.md) for contracts, units and limits.
[DIRECTOR.md](DIRECTOR.md) documents the JS project foundation.

```sh
uv run python -m pytest -q
node --test tests/*ui.js
uv build
```
