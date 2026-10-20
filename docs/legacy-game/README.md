# Legacy embodied lab

The embodied lab (`/game/` and the `game/` package) was removed from the Dagi
product on 2026-10-20. The operator folded that direction away and asked for a
minimal, stable core that can be improved in chat mode.

Nothing here is part of the running product. This directory keeps the lab's
operator documentation and the third-party license so the knowledge and the
attribution survive the removal.

## What stayed in the core

| Lab component | Core home |
|---|---|
| Bounded expression language (policy/metric expressions) | `dagi_core/expressions.py` |
| Skill contracts: validation, plan, dependency DAG | `dagi_core/learning.py` |
| Grading of a host-measured report, publish progress | `dagi_core/learning.py` |
| Mastery: applied evidence, current contract version, current binding, mastered prerequisites | `dagi_core/learning.py` |

The contract model is domain neutral: it grades a report that a trusted host
measured, and it never accepts a model-supplied success claim. The lab used
physics as that host; a file, test or deployment host can use the same model
with its own measurements.

## Documents in this directory

- `AGENT.md` — the lab's agent contract: skills, tools, sessions, limits.
- `AGENT_VERIFICATION.md` — how the lab's behaviour was verified.
- `LEARNING.md` — the Skill Fitness Lab: contracts, cases, receipts, mastery.
- `PHYSICS.md` — the lab's physical model and its limits.
- `DIRECTOR.md`, `DYNAMICS.md`, `GENESIS.md`, `VISUAL.md` — the lab's
  director, dynamics, scene-generation and rendering surfaces.
- `WALKING_FITNESS.json` — an example walking contract. It is an example, not
  an installed contract, and it is not evaluated by the core.
- `THIRD_PARTY_MOTION.txt` — the retained license and attribution for the
  planar running reference derived from DeepMimic.

## Rollback

- Git history holds the full package. The tag `legacy-game-base-a754c3b` marks
  the last commit that still contained it.
- The unfinished route/approach work is parked on the side branch
  `wip/game-route-approach` (never merged into `main`, never deployed).
- No persisted data was dropped: the game tables in the operator database are
  untouched, and a restored package can read them again.
