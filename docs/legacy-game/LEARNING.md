# Skill Fitness Lab (v8)

The missing distinction is **a tool completed / a candidate improved / a skill
met its contract / the composed goal passed**. None implies the next one.
This release implements those distinctions in the sandbox, rather than asking
the language model to remember what it promised eight turns ago.

## Runtime protocol

1. `game_train action=plan` declares the human goal, final target, dependency DAG,
   and versioned skill contracts. Each contract binds an executable project or
   policy, metrics, quality targets, ranking score, hard success predicate,
   guards and test cases. Missing programs can be written after planning.
2. `game_iteration skill=id` tests baseline and candidate against that contract.
   Dense metrics sample **every physical tick**. Local parameter search ranks
   training scores; validation can reject a change. It cannot select parameters
   on validation scores.
3. A candidate may publish when its guards hold and training fitness improves
   without validation score regression. It can still be **unmastered**. A
   previously mastered ability may not regress to failing its contract.
4. Mastery requires all declared training/validation cases, all targets, the
   success predicate, guards and currently verified dependencies. The final
   composed skill needs its own executable code and end-to-end tests.
5. Failures persist as experiments with measurements, worst case, contract/code
   bindings and latest failed source, including compile errors. Next turns can
   inspect and repair that source instead of reconstructing the attempt.
6. Budget or plateau exhaustion blocks practice. Mastery of the target stops
   autonomous paid turns; the local physical clock can continue. Existing model
   call/run budgets still apply. Neither reading nor restarting resets practice.

The model gets a bounded progress summary and a few scoped hypotheses, not a
transcript-sized stream of every simulated frame. Details are read on demand:

- `game_observe view=schema,path=learning` — exact contract.
- `game_observe view=learning` — goal, dependencies, criteria and measurements.
- `game_observe view=learning,path=skill_id` — contract and latest receipt.
- `game_observe view=learning,path=skill_id/main.js,offset=0` — failed source.
- `game_train action=evaluate,skill=id` — test the current saved executable.
- `game_train action=note,skill=id,attempt=receipt_id,hypothesis=...,next_change=...`
  — record a scoped hypothesis; a note is not verified knowledge.

An active plan routes physical/program edits through its current ready skill.
Omitting the skill argument cannot bypass a blocked plan. Cosmetic `art` edits
can remain independent. Criteria are hashed and audited; changing criteria,
source, physical configuration or prerequisite bindings makes old certificates
stale. During autonomous practice, measured criteria and the human target cannot
be weakened or relabelled; refining decomposition while retaining those criteria
is allowed. A human-directed revision is explicit and invalidates old evidence.

## What `fit` means

Use a **continuous numerical objective** to rank failed attempts and separate
**hard conditions** to decide whether the ability is usable. For walking, a
possible score is:

```
progress_m + 0.25 * longest_upright_s
           - 2 * slip_m - 0.01 * positive_muscle_work
```

The score alone cannot certify walking. Conditions should require sustained
upright time, alternating real support contacts, limited unsupported airtime,
limited slip, minimum travel and a stable end state. Guards distinguish actual
internal muscular control from assisted mode, static tethers, mechanism motors
or changed gravity. A character falling forward can gain displacement and still
fail the skill. A pretty animation supplies no evidence of contact or mastery.

Metrics accept safe expressions over current `s`, `prev`, and `initial` sensors.
`duration`, `longest` and `transitions` consume booleans; numeric reducers include
min, max, mean, sum, last and integral. Targets have optional min/max bounds.
`s.support` records actual supporting contacts, separately from generic limb
contact. Aggregation occurs at 60 Hz, even when the browser drops frames.

## Walking example, not a supplied walking ability

[WALKING_FITNESS.json](WALKING_FITNESS.json) is an **optional criteria example**:
balance → a discrete foot lift/replant → complete walking. No programs, motor
poses or progression are installed from it. It is inspectable through the
allowlisted source reader, with offsets. The language model still has to write
controllers, test them and satisfy the criteria.

The values (10-second trials, eight seconds upright, 100 pixels travel and slip
bounds) are illustrative starting requirements, not thresholds calibrated against
a reference walking controller. Review/tune them explicitly for the intended
body and task before practice; do not silently lower them after failures. Add
captured fallen-start cases for recovery: starting an unassisted body in a neutral
pose does not establish that it learned to stand up from the floor.

Cases reset controller memory/time and authored object poses. Captured body pose
is frozen at plan creation and remapped to current proportions. Explicit initial
velocities, timed impulses and project events provide distinct test conditions.
Validation cases are visible declared regression tests, not secret independent
holdouts. Passing bounded self-authored checks is not general certification.

## Memory layers

| Memory | Contents | Evidence status |
|---|---|---|
| Contract | Goal, DAG, metrics, cases, budgets, revision | Declared requirement |
| Receipt | Measured values, targets, source/physics binding, applied/experimental | Valid only for that binding |
| Failed source | Latest unsuccessful program, paged inspection | Working material, not an active ability |
| Hypothesis | Receipt-linked observation and next change | Unverified until tested |
| Certificate | Current passing receipt plus valid dependencies | Skill passed its stated contract |

Histories, case counts, expression size and simulation work are bounded. The UI
shows each skill's dependencies, attempt budget, fitness and actual metric values
against their required bounds. Failed criteria open for the focused skill. The local evaluation button runs the
saved contract without calling a model and rejects stale world/contract versions.

## Business-agent tasks

`grade_report(contract, report)` is a domain-neutral grader. The current runtime
adapter obtains reports from physics. The same grader can compare trusted test,
file, document or deployment measurements; a unit test demonstrates file counts
and test failures. **Those external adapters are not connected in this release.**
They must collect actual tool outcomes/artifacts and bind receipts to inputs,
code, environment and evaluator revisions. Do not expose an API where the acting
model can submit invented measurements and certify itself.

For a document pipeline the analogous graph is extract → normalize → calculate →
render → verify the assembled document. For deployment: prepare → configure →
start → health check → end-to-end request. Each child has its own observations;
the final skill tests the integrated result. This is the intended extension point,
not a claim that business-task verification is already implemented.

## Verification scope

Tests cover dense temporal metrics, real support vs contact, success vs progress,
validation regressions, dependency gating, stale certificates, indirect static
supports, budgets/plateaus, failed-source retention, persisted memory, autonomous
criterion locks and paid-turn stopping. Browser QA exercises plan → no-op failure
→ verified prerequisite → partial composition → rejected plateau → end-to-end
success, then reload and mobile layout. Its provider is explicitly scripted and
makes no external LLM call. It verifies the evaluation mechanism, not autonomous
learning or learned locomotion.
