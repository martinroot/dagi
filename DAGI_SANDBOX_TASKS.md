# Dagi Sandbox — Canonical Task Map

This is the single repository-level status map for the sandbox roadmap and cross-cutting runtime-awareness proposal supplied by Martin. Every new requirement or defect must be captured in a GitHub issue before implementation; update this file and the corresponding issue after each verified slice. Keep issue text in English. Close an item only after its acceptance checks pass and the issue's remote closed state is read back.

- Umbrella: [#16 — sandbox UI integration](https://github.com/martinroot/dagi/issues/16) (open until all remaining acceptance criteria are complete).
- Integration umbrella: [#20 — incremental 0.3.0 integration](https://github.com/martinroot/dagi/issues/20).
- Current branch: `main`.
- Verified code checkpoint: `f472a90a8fd3a18daeeb61740d10eb6a34f01fa2`; remote `main` matched before this roadmap-only update.
- Verification at this checkpoint: `pytest -q` — **152 passed**; Node UI — **21 passed**; `bash -n` and `git diff --check` passed; `uv build` produced wheel and sdist, including `dagi_core/workspace.py` and both static assets.
- Deployment boundary: no service restart or live `DAGI_HOME` migration has been performed. Backend changes are not claimed as active in the running service; #15 backup/restore rehearsal remains required before any live schema migration.

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
| CORE-02 — goal checks must use the goal owner's workspace | Open | [#35](https://github.com/martinroot/dagi/issues/35), parent #21 | Reproduced on `ff6fba0`; foreign root file passed child check |
| CORE-03 — CLI must honor the `DAGI_HOME` runtime lease before `/resume` | Open | [#22](https://github.com/martinroot/dagi/issues/22) | Reproduced; CLI recovery mutated a run while Web lease was held |
| CORE-04 — malformed built-in tool arguments must be recoverable errors | Open | [#23](https://github.com/martinroot/dagi/issues/23) | Reproduced; `read_file({})` became uncertain and blocked next turn |
| CORE-05 — command checks must bound output and clean up process trees | Open | [#18](https://github.com/martinroot/dagi/issues/18) | Timeout fixture now waits for a valid child PID before starting the timeout; 30/30 targeted runs passed on `10cfb3f`. Broader #18 acceptance remains open |

## Future layer

- Visual-world debugger as a read-only renderer over persisted entities/events: [#36 open](https://github.com/martinroot/dagi/issues/36). Do not start a game engine before the event model, tool cards, artifacts, and agent tree are stable.

## Runtime awareness proposal (SELF)

Full proposal: [`DAGI_SELF_AWARENESS_MVP.md`](DAGI_SELF_AWARENESS_MVP.md). This is bounded operational knowledge of identity, task, tools, evidence, limits, and corrective action; it makes no claim of subjective consciousness.

| ID | Status | GitHub issue | Dependencies / order |
|---|---|---|---|
| SELF-01 — bounded runtime identity, capability, and task-position context | Pending | [#38 open](https://github.com/martinroot/dagi/issues/38) | Session resolver #34 is done; goal-owner checks #35 remain; preserve runtime lease #22 |
| SELF-02 — tool semantics and persisted outcomes visible to the acting model | Pending | [#39 open](https://github.com/martinroot/dagi/issues/39) | After/alongside SELF-01 request-context work; depends on recoverable malformed arguments (#23) |
| SELF-03 — bounded corrective reflection and scoped evidence-backed lessons | Pending | [#40 open](https://github.com/martinroot/dagi/issues/40) | After SELF-01/02 and correct owning-workspace checks (#35) |

Execution order from the proposal: close prerequisites #34, #35, and #23 first; then implement SELF-01, SELF-02, and SELF-03 as separate, test-backed slices. Keep every observed runtime fact distinct from task-supplied text and model hypotheses.

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
- Do not deploy/restart the active service or migrate live `DAGI_HOME` as part of these code slices. Preserve cookie-session auth and verify logged-out API rejection.
- Treat command checks as service-user commands, not an OS sandbox; they stay operator-disabled unless explicitly enabled.
- Keep the async-child stash separate until iteration 6: `stash@{0}` (`WIP async child before sandbox iteration 6`).
