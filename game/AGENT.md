# Agent mode

Each new UI session posts `{"agent":true}` to `/api/game/sessions`. Existing saved worlds are not migrated or overwritten. Ordinary Core sessions retain their existing tools and BI/file capabilities.

The body waits for a task. Buttons and chat use `game.agent_runtime.command`. The scheduler persists active/queued execution IDs, goal, saved compositions, receipt-linked notes and checks in the existing SQLite session snapshot. A queue contains at most six skills. Failed checks block the remaining queue. Stop cancels active and queued work. Reconnecting resumes the authoritative elapsed time; completion is calculated by the server, never accepted from the viewer.

`game_observe {}` returns state and measured outcomes. A compact self passport is added to every model request, identifying the body, scheduler, motion source, viewer, configured model, capabilities and limits. It includes current task, outcomes and saved notes. No hidden chain of thought is stored or shown. This mode supplies structured state, not browser screenshots.

`game_skill` examples:

```json
{"action":"run","skill":"ladder","goal":"Подняться наверх","wait":true}
{"action":"run","steps":["vault","wall_flip","mantle"],"goal":"Тренировка паркура","wait":true}
{"action":"save","name":"Разминка","steps":["somersault","vault"]}
{"action":"run","skill":"Разминка","wait":true}
{"action":"note","receipt":"execution_id from a completed attempt","note":"Measured result and next hypothesis"}
{"action":"stop"}
{"action":"practice","enabled":true}
```

`wait:true` waits locally, interruptibly, without additional model polling. The web control API is asynchronous: `POST /api/game/sessions/:id/agent` accepts the same commands without waiting; `GET` returns progress, catalog, memory and evidence. These routes use existing authentication and origin checks. Browser input cannot provide a success score. No new credentials, model endpoint or autonomous API-spending loop is introduced.

Local practice, explicitly enabled by the human or requested agent action, selects the least repeated included skill after a three-second idle gap. It does not discover new skills or edit controllers. Named compositions reuse base skills; criteria cannot be overridden by the model. Outcomes are geometric checks of reference trajectories, not evidence of learned intelligence.

## Motion and evaluation

`static/motion.js` is shared by the Canvas renderer and isolated QuickJS checks. Bones retain exact lengths; IK checks reachability. Server checks sample at 120 Hz, check finite coordinates and continuity, plus skill-specific contacts, ladder placement, final posture, forward progress, ballistic COM and conserved angular momentum for flips. Receipts include values, thresholds, sample counts and a scope statement. They test packaged trajectories with fixed geometry; they do not replace a general collision solver or certify robustness to arbitrary obstacles.

The six primitives currently include their local practice geometry. Switching skills changes stations and local coordinates. There is no claim of seamless locomotion between stations. Contact labels are reference constraints; they are not force measurements. Grounded motion is authored contact animation, not torque-driven biomechanics. Only flip flight uses the analytic articulated angular-momentum integrator. Visual quality remains a human judgment.

The generic legacy physics/project runtime remains to load old data. It does not drive this new body. Old bundled films, video assets, premiere endpoints, scripted camera cuts and film controls were removed. Generic presentation validators remain for saved projects.

Running reference: DeepMimic planar projection, MIT attribution in `THIRD_PARTY_MOTION.txt`. Everything visible is vector Canvas geometry, gradients and layers; there are no generated raster backgrounds.
