# Agent 01 verification

Source baseline: `origin/main` at `e4634b1`. Verification: 2026-10-20.

- Python: **386 passed**, including 14 new agent checks for all six controllers, ordered execution, failure blocking, cancellation, isolated memory, compositions, API auth and a full Core → tool → completion → model-response exchange.
- JavaScript: **43 passed** across retained Core/legacy utility checks. The new UI is additionally covered by real-browser integration below.
- Chromium: six buttons; stop freezes the pose; a complete vault produces a server receipt; opt-in practice starts; JSON export downloads; new sessions are clean and old outcomes restore; 320 px viewport has no horizontal overflow; no JavaScript errors.
- Packaging: `uv build` produces wheel and source distribution. Wheel includes the shared motion implementation, server-side checks and retained MIT attribution. Old physical-film module and video assets are absent.
- `git diff --check`: clean.

The provider integration test uses a deterministic test provider. No paid or personal LLM credentials were used for verification. Live provider behavior depends on the operator's configured endpoint and model.

Reproduce:

```sh
uv sync --extra dev
uv run python -m pytest -q
node --test tests/*ui.js
uv build
# Optional: Playwright must be installed in the Node environment.
node scripts/verify_agent_browser.cjs /path/to/chromium
```

Motion checks certify the packaged reference trajectories and their geometry, not arbitrary collision robustness or learned muscular locomotion. Only the two flip flights have ballistic COM and angular-momentum conservation. Local practice repeats existing controllers; compositions reuse existing primitives.
