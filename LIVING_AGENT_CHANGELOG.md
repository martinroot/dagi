# Living agent mechanism — 2026-10-18

Base: martinroot/dagi main ac12ca43049b70489bcce6dabdc49f94650a9f7d.

The previous self-improvement path rewarded action/transition diversity. In session
19, adding climb commands without a ladder raised the score without creating a
new ability. This change removes that progression gate and the prescribed physical
curriculum. The model now chooses the purpose of its next iteration.

## Changes

- Opt-in server clock; durable agent-authored feedback controller runs every
  physical step between bounded model turns. Pause/play require no model calls.
- New game_design tool for mathematical/stateful feedback code, poses, joint
  forces, dynamic-object forces, physical material and appearance.
- Generic dynamic circle/rectangle bodies with mass, gravity, restitution,
  mutual contacts, skeleton contacts/impulses and support detection.
- Actual 240-frame controller trials, including later-time errors and memory.
  Every legacy behavior is tested without needing a skill card.
- Baseline/candidate diagnostics: travel, pose/support ratios, bone-length error,
  sampled speed jitter and foot slip. No score or claim of semantic superiority.
- Bounded 1–20 autonomous model turns, with operator call/budget limits per turn.
  Periodic requests retain session context and recent evidence. No fixed activity
  is embedded in the scheduler. Existing drafts can be repaired in later turns.
- Explicit human controls, saved-policy buttons, activity intent beside the body,
  real API/tool animation and the existing verified release/countdown.
- Fewer debug panels on the main screen; responsive desktop/mobile layout.
- Policies, memory and measured release history persist. A service restart pauses
  all worlds; it never automatically spends API budget or replays elapsed time.

## Validation

244 Python tests and 35 JavaScript tests passed. After the final contact-support
and responsive-layout adjustments, 62 relevant Python tests and 12 game UI tests
passed again. Wheel and source distributions build successfully.

A real Chromium check with an explicitly scripted provider covered publication,
continued physical movement after the provider turn, pause, no-model play, page
reload, saved controls, independent empty sessions, desktop/mobile and no browser
page errors or horizontal document overflow. This checks wiring and execution;
it does not evaluate live-model inventiveness or learning.

## Remaining limits

The physical engine is still an assisted 2D skeleton. It lacks rotating rigid
bodies, arbitrary hinges, articulated machines, full stacking and bone-segment
collision. Agent code can change controller mathematics and physical parameters;
it cannot hot-patch installed Python host source. Visual code can invent new
instruments but has no direct host access. Appearance metrics do not assess image
aesthetics; the model receives structured state, not screenshot vision.

A running world continues after closing its browser tab. Use Pause to stop it.
Money limits are per iteration, not aggregate across the whole development run.
Real model quality needs live provider sessions and human assessment of outcomes.
