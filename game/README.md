# Dagi Director — embodied agent lab

A bare physical stickman and an editable world. The model can author a multi-file
JavaScript project that synchronizes physical actions, camera, expressive face,
custom graphics and human-event reactions. There are no installed stories or
activity levels: the agent chooses and implements them through chat/iterations.

```sh
uv sync --extra dev
uv run dagi-web
```

Use the existing provider and web account; open `/game/`. Local projects run on
the server at 60 Hz without model calls or an open browser. **Начать развитие**
authorizes the selected number of API turns. **Продолжить занятие** runs existing
code locally; **Пауза** stops it and cancels the owned development turn. Restarting
the server pauses worlds and preserves saved source/state.

The agent has three tools: observe, submit/test/publish an iteration, and
play/pause. One iteration can edit a coherent project and its physical world.
Bodies, mechanisms and new physical appendages use actual rigid-body physics.
The viewer presents the camera and expression channels from that program.
**Общий план** overrides the camera; **Позвать агента** sends a local event.

Enable **Кадр мира для модели** for a vision-capable provider. It supplies a
small chronological canvas filmstrip, not the host desktop. Disable it for
text-only models. Drag objects or use arrows/space without tokens.

Read [DIRECTOR.md](DIRECTOR.md) for the exact contracts, setup and validation
boundaries. [GENESIS.md](GENESIS.md) describes the previous physical foundation.
A passing test establishes execution checks; live-model creativity and visual
quality must be evaluated separately with real provider calls and observations.

```sh
uv run python -m pytest -q
node --test tests/*ui.js
uv build
```
