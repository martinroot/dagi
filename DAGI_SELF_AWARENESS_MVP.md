# Dagi: Runtime Awareness and Bounded Reflection

Implementation proposal and GitHub issue drafts.

- Review date: 2026-10-17.
- Repository: https://github.com/martinroot/dagi
- Issues: https://github.com/martinroot/dagi/issues
- Reviewed commit: `fbe19969ecba4a6c9f27ef8f14b7cc797ea7e92e`.
- Method: static review of source code and issue descriptions. Tests were not executed for this review. Repository test counts are reported evidence, not independently verified results.
- Scope: practical knowledge of identity, tools, task position, evidence, limitations, and corrective action. This proposal makes no claim of subjective consciousness.

## 1. Recommendation

Dagi already persists much of the information needed for useful self-awareness. The first improvement is to expose that information to the acting model through a small, current runtime context.

Build three small slices:

1. **SELF-01:** runtime identity and task context.
2. **SELF-02:** tool semantics and explicit outcomes visible to the model.
3. **SELF-03:** bounded reflection and evidence-backed lessons.

Start with SELF-01 and one failed-check correction loop. Keep a knowledge graph, autonomous code modification, a separate critic on every action, and a new orchestration framework outside this MVP.

The first prototype should demonstrate an observable behavior change: the agent knows its assigned workspace, understands why its subtask matters, and changes its next action after a failed check. An hour or two is a prototype target, not a delivery estimate for all three issues or the existing core fixes.

## 2. Findings from the current implementation

| Finding | Source | Implication |
| --- | --- | --- |
| The default system prompt describes a terminal agent and is shared across execution paths. | [agent.py](https://github.com/martinroot/dagi/blob/fbe19969ecba4a6c9f27ef8f14b7cc797ea7e92e/dagi_core/agent.py), `SYSTEM_PROMPT` | The model lacks a reliable description of its actual entry point and role. |
| Request construction combines the system prompt, archived summary, and conversation history. | [context.py](https://github.com/martinroot/dagi/blob/fbe19969ecba4a6c9f27ef8f14b7cc797ea7e92e/dagi_core/context.py), `ContextBuilder.build` | Runtime identity, workspace, task position, and resource state are not assembled into a dedicated live context. |
| Tools contain retryability and effect-verification metadata; their provider specifications expose name, description, and parameter schema. | [tools.py](https://github.com/martinroot/dagi/blob/fbe19969ecba4a6c9f27ef8f14b7cc797ea7e92e/dagi_core/tools.py), `Tool` | Recovery policy exists inside the core but is not directly explained to the model. |
| Tool outcomes and presentation metadata are persisted, while the tool message contains the result text. | [state.py](https://github.com/martinroot/dagi/blob/fbe19969ecba4a6c9f27ef8f14b7cc797ea7e92e/dagi_core/state.py), `complete_tool_call` | The UI and core can have more explicit outcome information than the acting model. |
| Delegation supplies a task and explicit context, then requests a concise result and uncertainty. | [delegation.py](https://github.com/martinroot/dagi/blob/fbe19969ecba4a6c9f27ef8f14b7cc797ea7e92e/dagi_core/delegation.py) | The child has no required structured description of its purpose in the parent process or expected evidence. |
| Message search and reusable skills exist; there is no dedicated reflection/lesson lifecycle in the reviewed source. | [state.py](https://github.com/martinroot/dagi/blob/fbe19969ecba4a6c9f27ef8f14b7cc797ea7e92e/dagi_core/state.py), `search_memory`, `create_skill` | Reuse existing storage mechanisms where appropriate; add a small distinction between hypotheses and verified lessons. |

Existing foundations are useful: durable runs, explicit tool outcomes, shared budgets, context bounds, parent/child lineage, and deterministic goal checks. Extend them instead of introducing a parallel source of truth.

## 3. Core dependencies

| Existing issue | Relationship to this proposal |
| --- | --- |
| [#34 — session workspace resolution](https://github.com/martinroot/dagi/issues/34) | Resolve the actual execution workspace before presenting it as an authoritative fact. Cover Web, CLI, and resume. |
| [#35 — goal-owner workspace checks](https://github.com/martinroot/dagi/issues/35) | Verification must inspect the same workspace that owns the goal. A file belonging to another session cannot establish success. |
| [#23 — recoverable invalid tool arguments](https://github.com/martinroot/dagi/issues/23) | A malformed call must allow the agent to receive feedback and correct its arguments. Preserve uncertainty for genuinely unknown effects. |
| [#22 — CLI runtime lease](https://github.com/martinroot/dagi/issues/22) | Preserve a consistent runtime owner when recovering state. |
| [#17 — lifecycle extensions](https://github.com/martinroot/dagi/issues/17) | Potential later extension points. The MVP does not need to wait for a generic hook framework. |
| [#29](https://github.com/martinroot/dagi/issues/29), [#31](https://github.com/martinroot/dagi/issues/31), [#32](https://github.com/martinroot/dagi/issues/32) | Reuse the planned agent tree, goal controls, and diagnostics to display the new state. |

Workspace defects must be fixed before claiming child execution and verification have reliable self-awareness. Prototype the context serializer independently while these fixes are underway.

## 4. SELF-01: Runtime identity and task context

### Goal

Before acting, the agent can identify itself, its environment, its assignment, and what constitutes completion.

### Proposed context

The following is an illustrative new format, not an existing Dagi API:

```json
{
  "identity": {
    "agent_id": "agent-3",
    "session_id": 3,
    "run_id": "run-3",
    "parent_run_id": "run-1",
    "role": "executor"
  },
  "environment": {
    "entry_point": "web",
    "workspace": ".dagi-children/3",
    "shell_enabled": false
  },
  "assignment": {
    "overall_goal": "Prepare a verified report",
    "my_task": "Validate input data",
    "purpose": "The parent needs valid data before generating charts",
    "required_output": "validated.json",
    "acceptance_check_ids": ["check-7"],
    "return_to": "run-1"
  },
  "progress": {
    "phase": "verification",
    "last_verified_fact": "Input file exists",
    "evidence_ids": ["tool-call-42"],
    "blocker": "Output JSON validation failed"
  },
  "limits": {
    "remaining_provider_calls": 6,
    "remaining_cost_usd": null,
    "cost_status": "unavailable"
  }
}
```

### Implementation

- Add one small serializer, for example `runtime_context.py`.
- Derive identity, lineage, resolved workspace, enabled capabilities, and budget state from the actual runtime objects and persisted records.
- Take assignment fields from the saved user/parent task contract. If a field was not supplied, leave it unknown instead of inventing it.
- Keep application-generated facts separate from quoted task text, model hypotheses, and external tool content. Do not promote arbitrary task or memory content into privileged instructions.
- Inject the bounded context during request assembly. Rebuild it after resume and before subsequent provider calls so it cannot retain stale status or budget values.
- Expose `inspect_runtime` for on-demand details: enabled tools, relevant limits, current checks, and execution state. Use an explicit field allowlist; never serialize the full configuration or environment.
- Add a short trusted architecture description: Dagi runs a model/tool loop; the registry executes enabled tools; the state store persists outcomes; the goal controller evaluates configured checks; the parent receives child results. Derive optional feature availability from the running version.
- Keep task completion separate from provider response completion. Passing configured checks proves those checks passed; it does not establish claims outside their scope.

### Acceptance criteria

- [ ] Root and child requests contain their correct identities, lineage, and resolved workspaces.
- [ ] Web and CLI entry points are represented accurately.
- [ ] A resumed child receives its own workspace and current limits.
- [ ] Missing assignment information remains explicitly unknown.
- [ ] Secrets and unrelated session content are absent.
- [ ] Context remains within the configured size budget.

## 5. SELF-02: Tool semantics and verified outcomes

### Goal

The agent understands what each available tool can establish and how to respond to its outcome.

### Implementation

Keep standard provider tool schemas compatible. Add concise semantics to tool descriptions or a separate application-owned capability summary:

- Purpose and appropriate use.
- Input/output expectations.
- Side effects and current availability.
- Retry and recovery policy.
- Available effect verification and its limits.

Example for `write_file`:

> Writes UTF-8 content inside the assigned workspace. Success confirms the write operation. Task correctness requires the applicable acceptance checks. Recovery decisions belong to the runtime and may use an effect verifier.

During model request construction, represent tool results with a backward-compatible, bounded envelope containing `tool_call_id`, persisted `outcome`, and result content. Include artifact references and truncation indicators when available. Avoid rewriting source history or breaking assistant/tool message pairing.

Use distinct meanings:

| State | Required interpretation |
| --- | --- |
| `succeeded` | The tool operation reported success; task checks may still be pending. |
| `failed` | The operation has a known failure; correction may be possible. |
| `uncertain` | The effect is unknown; follow runtime recovery policy and inspect before any repeat. |
| Check passed | This specific check passed in its owning workspace. |
| Goal completed | All configured goal checks passed under the goal controller. |

An introspection response is descriptive. It cannot enable tools, grant permissions, override a budget, or change recovery rules.

### Acceptance criteria

- [ ] The model can receive explicit persisted outcomes without parsing arbitrary prose for success.
- [ ] Error information reaches the next model request when recovery permits continuation.
- [ ] A successful file write remains distinct from passing a content/schema check.
- [ ] Unknown custom tools retain a useful generic representation.
- [ ] Legacy text results and context truncation remain supported.
- [ ] Tool recovery behavior is unchanged by model-generated reflection.

## 6. SELF-03: Bounded reflection and evidence-backed lessons

### Goal

The agent compares intended and observed results, changes its next action, and retains useful experience with provenance.

### Reflection record

Store a short operational record, not a request for hidden reasoning:

```json
{
  "trigger": "acceptance_check_failed",
  "expected": "Create valid JSON",
  "observed": "File saved; JSON validation failed",
  "evidence_ids": ["tool-call-42", "check-7"],
  "cause_hypothesis": "Trailing comma",
  "next_change": "Fix syntax and repeat validation"
}
```

Observed status and evidence references come from the runtime. Cause and proposed correction may come from the model and remain hypotheses until tested. Validate record shape, scope, and size before persistence.

### Trigger policy

Reflect after a failed acceptance check, a repeated equivalent tool failure, or a significant task conclusion. Use the next normal model call when possible. Do not add a mandatory critic call after every successful tool.

Suggested bounded control policy:

1. Read the latest tool/check outcome.
2. If an effect is uncertain, preserve existing recovery behavior and do not automatically repeat it.
3. On a known failure, provide concise evidence and ask for a changed next action.
4. If the same normalized failure repeats twice without new evidence, require a different approach or a recorded blocker. Make the threshold configurable.
5. Persist the correction and whether the following check passed.
6. Create a scoped lesson candidate when the experience is reusable.

A failure fingerprint can combine tool name, normalized arguments, error category, and check identity. Exclude unstable timestamps. A changed action is not automatically a useful action; verify its effect.

### Lesson lifecycle

Use a small additive record in the existing store. Suggested fields:

`id`, `project_scope`, `trigger`, `lesson`, `evidence_ids`, `status`, `support_count`, `created_at`.

- First occurrence: `candidate`.
- A corrected outcome supports the lesson only within the observed conditions.
- Repeated independent support may promote it to `verified` under an explicit policy.
- Contradictory evidence can mark it `superseded` or `rejected`.
- Replaying the same stored event does not increase support count.
- Retrieve at most a few relevant lessons, with evidence and scope. A saved skill can be created later from a sufficiently supported procedure.
- Keep lessons within the applicable session/project access boundaries.

### Acceptance criteria

- [ ] Failed checks produce a concise corrective record with real evidence references.
- [ ] Cause hypotheses remain distinct from observed facts.
- [ ] Repeated equivalent failures cannot consume the entire budget through unchanged retries.
- [ ] Reflection respects shared budgets and the existing goal iteration cap.
- [ ] A crash or failed reflection save cannot replay a completed tool or change its recorded outcome.
- [ ] Lesson retrieval is bounded, scoped, and does not inject an entire history into each request.

## 7. Minimal implementation order

1. Fix workspace resolution and owning-session verification using #34 and #35; fix recoverable argument errors via #23.
2. Implement the runtime context serializer and inject it into existing request assembly.
3. Extend delegation with optional purpose, required output, and acceptance references. Keep the current task/context call compatible.
4. Expose persisted tool outcomes to the model.
5. Demonstrate one failed-check correction cycle using the existing goal controller.
6. Add repeated-failure detection and lesson candidates.
7. Display a small status card in the existing inspector: role, assigned task, phase, last evidence, blocker, next action, and latest reflection.

The status card reads saved state. Opening it does not execute tools or invent an agent's internal reasoning.

## 8. Verification scenarios

| Scenario | Required result |
| --- | --- |
| Child starts and later resumes | Both requests identify the same owning workspace and correct parent lineage. |
| Matching output exists only in the root workspace | Child acceptance fails. |
| `read_file({})` | A recoverable argument error is supplied; the agent can issue a corrected call. |
| File is written but contains invalid JSON | Write success is preserved; the check fails; the next action repairs the file. |
| Side effect may have occurred before interruption | Existing uncertain-outcome handling prevents blind replay. |
| Same failure repeats without new evidence | The agent changes approach or reports a blocker within its limits. |
| Model price is unavailable | Runtime context reports unknown cost, preserving the actual configured budget policy. |
| Prior mistake has a scoped lesson | A relevant candidate/verified lesson is retrieved with provenance; unrelated content remains absent. |

Use scripted providers for deterministic context, state, and recovery tests. Add a small model-driven smoke run to assess whether behavior improves; structural tests alone cannot establish reasoning quality. Report these two forms of evidence separately.

## 9. Context and cost limits

Use an initial target of **500–1000 additional input tokens** for the combined runtime summary, capability notes, and selected lessons. This is a design budget, not a measured result. It must fit inside the existing context limit and be tested against the models actually used.

- Keep stable capability descriptions short.
- Refresh dynamic state without appending an unlimited series of snapshots.
- Load detailed introspection only when needed.
- Retrieve a small number of relevant lessons.
- Count any reflection/compression calls against the existing shared budget.
- Avoid a new model call on the normal successful tool path.

Compare identical tasks with this layer enabled and disabled. Measure completion rate against meaningful checks, repeated failures, provider calls, total tokens, elapsed time, and known/unknown cost. Retain the layer only if observed reliability justifies its overhead.

## 10. GitHub tracking

The proposal is tracked as three separate, dependency-linked issues:

- **SELF-01:** [#38 — Add bounded runtime identity, capability, and task-position context](https://github.com/martinroot/dagi/issues/38)
- **SELF-02:** [#39 — Expose tool semantics and persisted outcomes to the acting model](https://github.com/martinroot/dagi/issues/39)
- **SELF-03:** [#40 — Add bounded corrective reflection and scoped evidence-backed lessons](https://github.com/martinroot/dagi/issues/40)

All three issues are open. Implement in the dependency order in §7, record focused and full-gate evidence in each issue, and update the canonical repository task map after every verified slice.
