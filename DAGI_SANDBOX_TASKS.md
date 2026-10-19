# Dagi Sandbox — Canonical Task Map

This is the single repository-level status map for the sandbox roadmap and cross-cutting runtime-awareness proposal supplied by Martin. Every new requirement or defect must be captured in a GitHub issue before implementation; update this file and the corresponding issue after each verified slice. Keep issue text in English. Close an item only after its acceptance checks pass and the issue's remote closed state is read back.

- Umbrella: [#16 — sandbox UI integration](https://github.com/martinroot/dagi/issues/16) (open until all remaining acceptance criteria are complete).
- Integration umbrella: [#20 — incremental 0.3.0 integration](https://github.com/martinroot/dagi/issues/20).
- Current branch: `main`.
- Deployed code commit: `cdabb01bce5c84c9e0cbc60d20534f20068a94c6`; remote `main` and production checkout were verified at this SHA before service start. The subsequent task-map update is docs-only.
- Verification: `pytest -q` — **225 passed**; Node UI — **35 passed**; JS syntax, Python compile, `bash -n scripts/test-focused.sh`, `git diff --check`, and `uv build` wheel+sdist passed. Public `index.html`, `game.js`, `studio.js`, and `component-host.js` return 200 and match checkout byte-for-byte; public unauthenticated API returns 401.
- Live `dagi-web` restarted successfully at 2026-10-18 12:37 EDT, PID `392301`, bound to `127.0.0.1:8765`; no unrelated proxy/DNS/firewall changes.
- Per operator instruction, all **18 test sessions** and their session-scoped messages, 73 runs, 498 tool executions, provider metadata, events, 15 game worlds, 14 context archives, and 52 tool reflections were deleted from the live DB. Post-reset counts are zero; SQLite integrity and foreign-key checks pass. Global `skills` count was 0 before/after; external profile skills/memory/config were untouched.
- Protected rollback snapshot retained at `/home/dagi/.dagi/backups/state-pre-self-improve-rollout-cdabb01-20261018T122744-0400.sqlite3` (`0600`, parent `0700`); it contains pre-reset session data and remains recoverable until release acceptance. No session export archive was delivered; scratch export and rehearsal copies were removed. No live provider call was made.

## Ten implementation iterations

| Iteration | Scope | Status | GitHub tracking |
|---|---|---|---|
| 1 | Reconcile HEAD; reproduce CORE-01…04; record workspace/event contracts | Done | #21–#23, #34–#35 |
| 2 | Canonical UI state, snapshots/cursors, dedupe and reconnect | Done | #24, #28 |
| 3 | Updating generic tool cards and explicit outcomes | Done | #25 |
| 4 | Structured tool metadata and built-in renderers | Done | #26 (closed) |
| 5 | Safe live chat, Markdown, drafts, input and autoscroll | Pending | #27 |
| 6 | Agent tree, child-resume/workspaces, async delegation | Pending | #29; foundation #8/#16 |
| 7 | Safe per-session artifacts and workspace browsing | Pending | #30 |
| 8 | Goal controls and acceptance-check progress | Pending | #31; backend #13 complete |
| 9 | Diagnostics, skills, clone semantics, CORE-05 cleanup | Pending | #32, #18 |
| 10 | Responsive/accessibility polish, deterministic demos, browser acceptance | Pending | #33 |

## Sandbox feature issues

| ID | Status | Issue | Verified implementation/evidence |
|---|---|---|---|
| SB-01 — stable UI state keyed by session/run/tool call; saved message IDs; no duplicate replay | Done | [#24 closed](https://github.com/martinroot/dagi/issues/24) | `b44931e`, `eff6f5d`; snapshot/replay tests; included in latest 141-test suite |
| SB-02 — one updating generic tool card with status, duration, result/error and unknown-outcome handling | Done | [#25 closed](https://github.com/martinroot/dagi/issues/25) | `371a42f`, `2484c12`; Node UI regressions and explicit tool outcome event, included in latest 141-test suite |
| SB-03 — backward-compatible structured presentation metadata and specialized built-in renderers | Done | [#26 closed](https://github.com/martinroot/dagi/issues/26) | `33657ab` metadata persistence; `e49e401` read; `c579232` write/list; `947e263` memory; `8bf6bbf`, `062d265`, `2decc50` skills; `dd96a3d` commands; `b9f91e2` delegation; `2b5287a` bounded diff; `084af5f` raw text fallback. Safe file-browser navigation remains in SB-07/#30 |
| SB-04 — truthful live chat, safe Markdown, drafts, input and history-preserving scroll | Pending | [#27 open](https://github.com/martinroot/dagi/issues/27) | Not started |
| SB-05 — consistent snapshot cursor, bounded event paging, gap-free SSE recovery and long-run replay | Done | [#28 closed](https://github.com/martinroot/dagi/issues/28) | `55d7f09`, `49ae883`; tests cover snapshot/subscription gap, 501 events over multiple pages, terminal cursor ordering |
| SB-06 — parent/child tree and asynchronous delegation | Pending | [#29 open](https://github.com/martinroot/dagi/issues/29) | Existing child lineage/workspace/inbox foundation: `4a1cebd`, `ff6fba0`; async-spawn WIP remains safely stashed and is not deployed |
| SB-07 — safe artifact browser scoped to session workspace | Pending | [#30 open](https://github.com/martinroot/dagi/issues/30) | Not started |
| SB-08 — goal creation, live checks and valid stop/resume UI | Pending | [#31 open](https://github.com/martinroot/dagi/issues/31) | Backend goals are in #13; UI not started |
| SB-09 — diagnostics, skills catalog and safe session clone semantics | Pending | [#32 open](https://github.com/martinroot/dagi/issues/32) | State clone primitive exists; UI/semantics not completed |
| SB-10 — accessible responsive UI, deterministic demos and real-browser acceptance | Pending | [#33 open](https://github.com/martinroot/dagi/issues/33) | Not started |

## Confirmed core defects

| ID | Status | Issue | Finding/required fix |
|---|---|---|---|
| CORE-01 — child run writes must use the owning session workspace | Done | [#34 closed](https://github.com/martinroot/dagi/issues/34), parent #21 | `resolve_session_workspace()` used by Web runs and CLI/resume; rejects traversal and symlink escapes. Web/CLI integration and shared resolver regressions; commit `f472a90`, pytest 152 and Node UI 21 passed |
| CORE-02 — goal checks must use the goal owner's workspace | Done | [#35 closed](https://github.com/martinroot/dagi/issues/35), [#21 closed](https://github.com/martinroot/dagi/issues/21) | `start_goal()` and each verification/resume resolve the goal session via `resolve_session_workspace()`; root-only file and symlink escape regressions. Commit `5262012`; full pytest 154, Node UI 21, build passed |
| CORE-03 — CLI must honor the `DAGI_HOME` runtime lease before `/resume` | Open | [#22](https://github.com/martinroot/dagi/issues/22) | Reproduced; CLI recovery mutated a run while Web lease was held |
| CORE-04 — malformed built-in tool arguments must be recoverable errors | Done | [#23 closed](https://github.com/martinroot/dagi/issues/23) | Built-in required fields/types validated before handlers; malformed calls persist as failed and permit corrected provider/user turns. Custom tools and genuine uncertain outcomes unchanged; `c0841bf`, pytest 156, Node UI 21, build passed |
| CORE-05 — command checks must bound output and clean up process trees | Open | [#18](https://github.com/martinroot/dagi/issues/18) | Timeout fixture now waits for a valid child PID before starting the timeout; 30/30 targeted runs passed on `10cfb3f`. Broader #18 acceptance remains open |

## Future layer

- Visual-world debugger as a read-only renderer over persisted entities/events: [#36 open](https://github.com/martinroot/dagi/issues/36). Do not treat the separate physics game as satisfying or closing this renderer issue.
- User-directed experimental embodied physics lab: [#43 closed](https://github.com/martinroot/dagi/issues/43), deployed at `/dagi/game/` through existing session auth and APIs.
- Studio v2.1 and agent-authored visual components: [#45 closed](https://github.com/martinroot/dagi/issues/45), code `5a86a0d`; authored JS runs in an opaque browser worker/iframe with validated output, not in the Python service or on the host.
- Session-8 source-path and self-improvement budget guidance: [#46 closed](https://github.com/martinroot/dagi/issues/46), code `b28c4b4`; unique allowlisted basenames resolve canonically, ambiguous names remain rejected, traversal stays blocked.
- World-12 loop/goal reliability: [#47 closed](https://github.com/martinroot/dagi/issues/47), code `1f1f268`; configured provider budget now sets a compatible tool-round ceiling and goal feedback carries signed direction/progress. Its original read-only diagnosis was preserved; a later operator-authorized test-session reset is recorded under #48.
- Embodied self-improvement and session audit export: [#48 open](https://github.com/martinroot/dagi/issues/48), code `cf993cb` (deployed with docs commit `cdabb01`); guarded physical-skill progression, two local execution cycles, replayable motion/avatar cues, and authenticated session JSON export are live. All 18 test sessions were reset on the operator's request; post-reset DB integrity, counts, auth gate, and public assets were verified. The protected rollback backup still holds pre-reset data; no live model-driven smoke has been run.

## Genesis turn-cap burn-down (2026-10-19)

Two identical failures after Genesis v4 went live, both ending `provider call limit reached` before the task finished:

| Issue | Session | Cause | Fix commit |
|---|---|---|---|
| [#56](https://github.com/martinroot/dagi/issues/56) | 24 | `game_iteration` change errors surfaced legacy `game_evolve` field unions, inviting legacy-shaped retries; description lacked exact schemas; cap was `min(8, operator)` with no discovery headroom | `c197a1a` — schema-first change rejection, inline schemas in the description, shared `game_call_cap` helper (12-call headroom) |
| [#57](https://github.com/martinroot/dagi/issues/57) | 25 | The schema view taught the ambiguity (field groups without the `operation` key); the parser rejected recognizable encodings (JSON string, `type` alias, `{"policy":{...}}` wrapper, flattened policy fields) one call at a time | `35bde92` — `_normalize_changes` accepts the four encodings and canonicalizes them; schema view and description document the per-change `operation` key with examples |

Both slices are RED/GREEN with regression tests in `tests/test_game_genesis.py`; the full gate ran before each push (263 then 270 pytest, 35 Node UI, wheel/sdist, syntax/diff). Deployments restarted only after live runs reached idle, with protected backups. Unknown change shapes still fail with the design/visual operation list — tolerance is for recognizable encodings, not for skipping validation.

## Repository description as an agent-debugging instrument (2026-10-19)

Per operator direction the README is reframed: **the sandbox is an instrument
for debugging an AI agent, not a game**. Title is "Dagi — a debugging instrument
for an AI agent"; the body argues why a physical world is the right debugger
(claims become measurements; every change is a baseline experiment; state and
memory inspectable; failures isolated, not narrated; the agent's own
observe→trial→publish→reflect loop mirrors the human's). The top of the file
embeds the workshop loop as an inline autoplaying GIF
(`docs/examples/workshop-debug-loop.gif`, ~5.2 MB, 12 s, 800 px, 10 fps, 96
colors, converted from the operator's `physics-workshop-demo.rar` recording —
byte-identical to the published `workshop-physical-test-bench.webm` source) so it
plays without a click; the raw recordings remain linked below for full quality.
Operational sections (features, safety, run/env, delegation, sandbox, workshop,
custom tools, verification, layout, provenance) were preserved verbatim; the
sandbox/workshop sections were renamed to their debugger roles. Caption states
honestly: scripted fixture, no live model — the instrument, not intelligence.
RAR extraction used a locally downloaded `unrar` .deb (no root) — cleaned up
afterwards.

## Repository concept description (2026-10-19)

Per operator direction the README is fully rewritten and the videos sit at the
top, before any prose. All available operator-supplied recordings are published
under `docs/examples/`: `physical-workshop-fixture.mp4` (the operator's own
recording: rope → wheel → weight, cart with motors, mountains, the
«торс закреплён / ходьба не обучена» banner), `workshop-physical-test-bench.webm`,
`workshop-unassisted-start.webm` (v6 verification set) and
`director-scripted-demo.webm` (v5 verification set). No poster frames are used;
each video is a plain link with an honest caption — scripted fixtures, no live
model, execution evidence only. The concept body follows: body-is-the-agent,
craftable world, craftable/tested/versioned abilities, visible bounded memory,
tools exercised on physics; the operational sections (features, safety, run/env,
delegation, sandbox, workshop, custom tools, verification, layout, provenance)
are kept complete. Note: the Genesis v4 archive's `scripted-motion.webm` could not
be re-extracted — that archive's file was intermittently invisible on this host
and the scratch copy was already cleaned; re-supply it if that recording is
wanted in the repo.

## Repository concept description (2026-10-19)

The README now leads with the project concept instead of the implementation
inventory: the agent's sandbox is a physical world — the body is the agent, the
world is craftable (mechanisms, materials, scenery), abilities are
craftable/tested/versioned (controllers, trials, countdown publication), memory
is visible and bounded (policy memory, transcripts, skills, passport), and tools
are exercised on physics rather than mocked payloads (`game_observe` /
`game_iteration` / `game_life`). An example section embeds the operator's
workshop fixture video (`docs/examples/physical-workshop-fixture.mp4`, scripted
physics fixture — torso fixed, walking not learned; execution evidence only, no
live model) and states that boundary explicitly. The layout section gained the
workshop modules (`game/rigid.py`, `game/embodiment.py`, `game/mechanics.py`,
`game/workshop.py`, `game/director.py`) and `docs/examples/`.

## Skill Fitness Lab v8 integration (2026-10-19)

Operator archive `dagi_v8.zip` (0.7.0) supplied sources only — no patch, no START_HERE. Their snapshot already contained every prior integration through the README rewrite, so the change set (11 modified, 5 new: `game/learning.py`, `game/static/learning.js`, `game/LEARNING.md`, `game/WALKING_FITNESS.json`, learning tests) was reviewed file-by-file and applied. The snapshot's stale `cdabb01`-era task map was deliberately not copied.

The distinction this version implements in the engine instead of in prompts: **tool completed ≠ candidate improved ≠ skill met its contract ≠ composed goal passed**. `game_train` plans a human goal into a dependency DAG of versioned skill contracts (metrics, targets, ranking score, hard predicate, guards, test cases); trials sample dense per-tick metrics; local search ranks *training* fitness while validation can only reject. Publication with improved fitness still leaves a skill explicitly unmastered; mastery needs every case, target, predicate, guard and verified dependency, and the final composition needs source-bound receipts. Failed attempts (compile errors included) persist with their source so later turns repair, not reconstruct. Criteria are hashed — autonomous practice cannot weaken measured criteria or the human target, and revisions invalidate old receipts. Budget/plateau exhaustion blocks practice; mastered targets stop paid turns while the local clock may continue. Gate: 360 pytest / 49 Node UI / wheel 0.7.0. Deployed `f2cd7af` (PID 454210) with protected backup. Issue #61.

## Vector Character Studio v7 integration (2026-10-19)

Operator archive `dagi-vector-character-v7-20261019.zip` on base `1fd30e3`, package 0.6.0. Conflict check: `git apply --3way` clean on 25 of 26 files; only README.md conflicted (the incoming patch targeted the pre-instrument README while HEAD carried the debugging-instrument rewrite) — resolved by keeping the instrument framing and merging the v7 additions (fixture link + Vector Character Studio section). New surface: ribs/spine/pelvis/skull with real shoulder/hip attachments on a rigid torso where bone length, capsule radius and mass actually change physics; fully vector Canvas2D rendering (muscle/skin/bone/metal surfaces, shared lighting, gradient materials, shadows, atmospheric parallax, wind/grass) with one vector API shared by scene layers and agent JS projects; body/face camera framing decoupled from the physics clock. Debugger contract: cosmetic edits verified to preserve motion, geometry edits remap the pose and are re-tested; no gait or stance holding is shipped. Gate 333 pytest / 46 Node UI / wheel 0.6.0. Deployed `7075457` (PID 450471) with protected backup; README statements recorded in issue #60.

## Genesis v4 integration (2026-10-19)

Source: operator archive `dagi-genesis-v4-20261018.zip` (snapshot `2de5d6c4989a0d6b5fadf1a1feb538d3cf4f9de4`, base `69ce1e3`) plus `dagi-genesis-v4.patch` and Chromium verification materials (scripted provider; not a live LLM).

Merge conflict check: `git apply --3way --check` applied **cleanly to all 24 patch files** — the archive's base equals the repository HEAD at the time of integration, so no overlap resolution was needed.

What changes: the physics bottleneck moves to Pymunk 7.2 / Chipmunk — rigid capsule limbs, pivot constraints, rotary posture motors, whole-limb collision, friction, rotation, stacking and two-way impulses, with the skeleton still motor-assisted. A dedicated server thread advances physics at 60 Hz (two substeps) without SQLite/model calls; `/api/game/sessions/<id>/frames` streams SSE state (≤30 Hz) that the browser interpolates; semantic mutations stay durable before visibility with two-second motion checkpoints. The main model-facing tools become `game_observe` / `game_iteration` / `game_life` (legacy tools remain registered but hidden from new game requests); `game_iteration` accepts one coherent edit package (1..8 changes), optional local `play` and a bounded local parameter `search` over measured trial metrics. World migration converts web worlds to Chipmunk without deleting authored programs; a late live policy failure disables that controller and keeps the world settling instead of freezing. Canvas rendering gains DPR scaling, contact/altitude shadows, object orientation, expressive eyes and trails; an optional «Кадр мира для модели» sends a real downscaled canvas image to vision-capable models (off for non-vision models; caching the frame never calls the model).

Limitations recorded from GENESIS.md: still assisted 2D physics, not learned biomechanics; installed Python engine source is not hot-patched from chat; a hard crash can lose ~2 s of motion; paid iterations never auto-resume after service restart; local search scores are experiment-specific evidence, not a universal ability score. New dependency `pymunk==7.2.0` is declared in pyproject and installed via `uv sync`.

Gate: 260 pytest passed, 35 Node UI passed, wheel/sdist/syntax/diff checks passed. Live deployment requires the usual protected backup plus a migration rehearsal on a DB copy, because the existing operator sessions' worlds must convert to the Chipmunk representation.

## Living agent mechanism integration (2026-10-18)

Source: operator archive `dagi-living-agent-20261018.zip` (snapshot `bd28753`, branch `feat/living-agent`, base `ac12ca4`), plus `dagi-living-agent.patch` and Chromium verification screenshots taken with a fixed scripted provider (not a live LLM).

Merge conflict check (`git apply --3way` against `b5486b3`): textual conflicts in `game/bridge.py`, `game/static/game.js`, `game/studio.py`; clean three-way in `game/world.py`, `tests/test_game*.py*`, `dagi_core/web.py`, `game/static/index.html`, `game/static/studio.js`, `game/README.md`. All seven files touched by the earlier #49–#53 slices also appear in the incoming patch, so the living-agent version (a designed replacement of the game progression subsystem, validated by its author at 244 Python + 35 JS tests) was taken wholesale for every patch-touched path; this task map's own sections are preserved.

Consequences recorded for rollback: the incoming design deliberately removes the complexity-score release gate and the prescribed physical curriculum in favour of agent-authored `game_design` feedback policies, a bounded 1–20 iteration model scheduler with operator call/budget limits, dynamic bodies with contacts, and measured release diagnostics (travel, pose/support ratios, bone-length error, jitter, foot slip). The #49 contact-refusal, #50 improvement checks and #53 verified score are superseded by this mechanism and are not carried into the merged tree; the engine's contact/support detection replaces the score-gaming vector.

Gate on the merged tree: 244 pytest passed, 35 Node UI passed, wheel/sdist build and syntax/diff checks passed. Session #19 (operator test session) preserved through deployment rehearsal.

## Session #19 review: embodied interaction quality (user score 1/10)

Review of the persisted "Чистый мир #19" log found three root causes: climbing was a scripted y-nudge with no body↔object contact; the complexity score grew from action-name counting while behavior did not change; and the UI could not show contact, climb or activity. Fixed as five issue-linked, independently revertable slices, each RED/GREEN with focused tests, pushed to `main`:

| ID | Status | GitHub issue | Commit |
|---|---|---|---|
| Contact physics: climbable zones, contact-gated climb, alignment to the rail | Closed | [#49](https://github.com/martinroot/dagi/issues/49) | `133c22d` |
| Honest verification: behavior trials, `interaction_verified`, `meaningful_displacement`, `complexity_delta_source` | Closed | [#50](https://github.com/martinroot/dagi/issues/50) | `69bb419` |
| Behavior schema: 16 steps, phase labels, bounded program chaining | Closed | [#51](https://github.com/martinroot/dagi/issues/51) | `302a735` |
| Live visibility: contact indicator, climb pose, activity status, verified score | Closed | [#52](https://github.com/martinroot/dagi/issues/52) | `bad5057` |
| `complexity_score` from verified physics (travel, contact, posture), not action counting | Closed | [#53](https://github.com/martinroot/dagi/issues/53) | `44bbf78` |

Closure gate per issue set: full pytest 236 passed, Node UI 36 passed, JS/Python/shell syntax and `git diff --check` passed; each issue closed only after remote readback of body/state. Consequences for self-improvement: a claimed climb without ladder contact is refused and blocks commit; repeats/renames cannot raise the gate score; score growth requires measured physical achievement. Live rollout after each slice keeps the operator's live test session intact.

## Runtime awareness proposal (SELF)

Full proposal: [`DAGI_SELF_AWARENESS_MVP.md`](DAGI_SELF_AWARENESS_MVP.md). This is bounded operational knowledge of identity, task, tools, evidence, limits, and corrective action; it makes no claim of subjective consciousness.

| ID | Status | GitHub issue | Dependencies / order |
|---|---|---|---|
| SELF-01 — bounded runtime identity, capability, and task-position context | In progress | [#38 open](https://github.com/martinroot/dagi/issues/38) | `dd718d9` bounded per-request context; `1ba992e` allowlisted `inspect_runtime`; `de65971` persists optional delegation purpose/output/check IDs through resume. Structural tests pass, including actual CLI child resume. Remaining: a model-driven smoke, not run without operator approval for possible provider cost |
| SELF-02 — tool semantics and persisted outcomes visible to the acting model | Done | [#39 closed](https://github.com/martinroot/dagi/issues/39) | `6f4c9f2` adds bounded persisted outcome envelopes with artifact/truncation data and legacy fallback; `9cd9381` describes recovery/effect-verifier semantics while preserving provider JSON schemas. Full pytest 164, Node UI 21, build passed |
| SELF-03 — bounded corrective reflection and scoped evidence-backed lessons | Done | [#40 closed](https://github.com/martinroot/dagi/issues/40) | `042259f` persists bounded failure observations/evidence; `0f6a4b7` adds normalized fingerprints and configurable blocker (`DAGI_GOAL_REPEAT_FAILURE_THRESHOLD`, default 2, range 1–10); `ce5d85f` adds candidate/verified session-scoped lessons; `92c602b` rejects matching contradictory actions with provenance. Final gate: pytest 173, Node UI 21, build passed |
| SELF-04 — bounded runtime/reflection inspector card | Done | [#41 closed](https://github.com/martinroot/dagi/issues/41) | `76d8785` adds the allowlisted read-only API summary from saved session/run state; `5ef0359` adds GET-only card/refresh with unknown fallbacks, separate tool/check/goal status, scoped lesson evidence, and safe text rendering. Full pytest 177, Node UI 23, build passed |
| SELF-05 — reflection on repeated non-goal tool failures and task conclusions | Done | [#42 closed](https://github.com/martinroot/dagi/issues/42) | `2cb9393` persists bounded repeated-failure reflections, exposes them in refreshed runtime context, blocks unchanged retries after the configured threshold, and records tool-run conclusions with `goal_status=unknown`. Full pytest 175, Node UI 21, build passed |


Execution order from the proposal: prerequisites #34, #35, and #23 are closed. SELF-01 structural context and SELF-02 tool outcomes are implemented; SELF-01 remains open for a bounded model-driven smoke, pending operator approval due possible provider cost. SELF-03 goal-check reflection/lessons (#40), non-goal repeated-failure/run-conclusion records (#42), the inspector card (#41), embodied game (#43), Studio v2.1 (#45), and session-8 source-guidance fix (#46) are complete. #47/#48 code and full test gates are pushed; #48 is live on `dagi-web`, and the 18 test sessions were reset with a protected rollback snapshot retained. No live model/provider smoke was performed. Resume the preserved backlog at CORE-03/#22, then ITER-05/SB-04/#27; keep the stashed async-child WIP untouched until its separate review.

## Current SB-03 sequence

1. Persist optional presentation metadata atomically with tool outcomes/events (done in `33657ab`).
2. Add structured `read_file` result and renderer (done in `e49e401`: path, byte size, line numbers, truncation, artifact reference).
3. Add `write_file`/`list_dir` renderers (done in `c579232`); capture prior file content only with a strict size cap before offering a diff.
4. Add memory renderer (done in `947e263`) and skills catalog/load/create renderers (done in `8bf6bbf`, `062d265`, `2decc50`).
5. Add delegation/command renderers with explicit policy and structured diagnostics (done in `b9f91e2` and `dd96a3d`).
6. Keep generic fallback and make original tool text available for transformed renderers; metadata size/shape, legacy extension compatibility, and safe text rendering are covered (`084af5f`).

## Operational constraints

### Fast issue-level testing (DX)

- [#37 — focused test runner](https://github.com/martinroot/dagi/issues/37) is closed; `scripts/test-focused.sh` accepts pytest selectors and an optional Node UI pattern, runs both in parallel, and reports each failure.
- Focused diff example completed in **1.26 s**; prior full-suite baseline was **32.24 s**. This improves red/green iterations without removing or weakening tests.
- Before issue closure/release, still run full pytest + Node UI + package build. `README.md` documents both loops.

- Continue on `main` in small, reversible, issue-linked commits; push each green slice and verify local/remote SHA.
- Live deployment is allowed only when the user explicitly requests it. For #43/#45/#46, the existing authenticated HTTPS `/dagi/` route and loopback listener were reused; no Nginx, DNS, firewall, or unrelated service was changed. Unauthenticated game APIs return `401`.
- Before #45, active runs/tools were checked and the v1-world upgrade/restore rehearsed on a protected copy; rollback snapshot `/home/dagi/.dagi/backups/state-pre-studio-v2.1-5a86a0d-20261018T072827-0400.sqlite3` is retained. Before #46's code reload, a newer protected snapshot was saved at `/home/dagi/.dagi/backups/state-pre-session8-fix-b28c4b4-20261018T074554-0400.sqlite3`.
- #47/#48 are pushed to remote `main` but not installed in the live service. The existing #46 snapshot predates world-12 activity; after explicit deployment approval, make a fresh backup and repeat idle-work/API/auth checks before restarting.
- Treat command checks as service-user commands, not an OS sandbox; they stay operator-disabled unless explicitly enabled.
- Keep the async-child stash separate until iteration 6: `stash@{0}` (`WIP async child before sandbox iteration 6`).
