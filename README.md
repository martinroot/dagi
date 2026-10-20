# Dagi — агентская среда

Новая рабочая поверхность `/game/`: один 2D-персонаж, чат с Core и шесть базовых навыков. Старые видеоролики, кино-премьера, раскадровка и режиссёрские пресеты удалены.

| Навык | Выполнение |
|---|---|
| `somersault` | Разгон, приседание, сальто, колено и кулак у пола |
| `wall_flip` | Два шага по стене, обратное сальто, стабилизация |
| `vault` | Опора рукой на тумбу, перемахивание, продолжение бега |
| `ladder` | Поочерёдная опора на реальные перекладины, выход наверх |
| `mantle` | Зацеп края, подтягивание, силовой выход, заброс ноги |
| `drive` | Подход, открывание двери, посадка, руки на руле |

Модель планирует и вызывает `game_skill`. Тот же серверный инструмент обслуживает кнопки. Очередь, результаты и заметки сохраняются отдельно для каждой сессии в SQLite. Завершение и проверки определяет сервер; браузер только рисует общую исполняемую траекторию.

Это **готовые контактные анимационные навыки**, а не обученные мышечные контроллеры. Полёты двух сальто используют баллистику центра масс и сохранение момента импульса. Проверки подтверждают геометрию штатных траекторий, не произвольные столкновения, красоту или общее владение паркуром. Смена навыка подготавливает отдельную площадку и меняет локальную систему координат; непрерывная навигация по общей карте пока не реализована.

Чат использует только API и модель, настроенные оператором. Кнопки, очередь, проверки и включаемая человеком локальная практика не вызывают модель. Практика повторяет готовые навыки; сама по себе она не обучает новые движения.

## Быстрый старт

```sh
uv sync
uv run dagi-web
```

Настройте API и веб-авторизацию как описано ниже. Откройте `/game/` и нажмите «＋ Сессия». Старые сохранённые миры не перезаписываются; для них новый интерфейс предложит создать агентскую сессию.

Попробуйте в чате: «Поднимись по лестнице, затем сделай сальто. Дождись завершения, проверь результаты и сохрани вывод». Или: «Сохрани связку разминка: перемахивание, сальто от стены, силовой выход».

Контракты, примеры JSON и ограничения: [game/AGENT.md](game/AGENT.md). Общие физические механизмы Core сохранены для совместимости старых проектов, но не выдаются за контроллер нового тела.

## Core features

- One streaming OpenAI-compatible API adapter.
- An agent loop for text, tool calls, tool results, and follow-up responses.
- SQLite transcript, FTS5 memory search, and persistent reusable skills.
- Durable run records with `completed`, `error`, `limit`, and `cancelled` outcomes.
- Events correlated by session ID, run ID, and tool-call ID.
- Provider usage is persisted per call and aggregated per run as actual, estimated, mixed, or unavailable; missing usage is never stored as zero.
- Configurable per-model prices, provider-call limits, and monetary run budgets.
- Bounded model-context assembly with tool-result truncation, source-preserving history summaries, and exact request snapshots.
- Stream finish reasons are validated; partial responses are stored as incomplete, and unfinalized tool calls are never executed.
- Publicly extensible tools with structured results and persisted recovery metadata.
- Bounded parent/child agent delegation with separate sessions, explicit context transfer, and a shared budget.
- Workspace-scoped file tools; a tool call is persisted before its side effect.
- A terminal CLI with session listing/resume plus a separate loopback visual sandbox.
- Interrupted tool actions are recovered by state: safe pending calls may resume, while unknown outcomes are never replayed automatically. Legacy tool-result text without an explicit persisted outcome remains uncertain; new tool completion commits the result message, outcome, and run event atomically.

The runtime has one direct dependency, `openai`; SQLite and the CLI use the
Python standard library. There is no messaging gateway, MCP, cron, voice,
profile, or remote-backend integration in this version. The workshop
additionally uses `pymunk` (Chipmunk rigid bodies) and `python-quickjs-ng`
(server-side agent JavaScript), both installed by `uv sync`.

## Safety

`DAGI_ENABLE_SHELL` is disabled by default. When enabled, every CLI shell command requires interactive approval; command text is escaped before display. The workspace constrains file tools but is not an OS-level sandbox. The bounded goal-check runner uses argv without a shell, a fixed credential-free environment, process-group cleanup, and capped output; any command check is still privileged code executed as the Dagi service user, not an OS sandbox. Keep `DAGI_ENABLE_CHECK_COMMANDS` disabled unless an operator explicitly opts in on a trusted installation; a request payload cannot change this setting. Only one `dagi-web` process may own a given `DAGI_HOME`; an owner-only runtime lock prevents duplicate recovery/workers. The database is created with mode `0600`; the default `~/.dagi` directory is `0700` on POSIX. An explicitly selected existing `DAGI_HOME` keeps its existing directory permissions. API keys, session password hashes, and worker tokens are excluded from `Config` repr and are never written to the repository or database. Agent JavaScript runs in a bounded interpreter (heap, stack, CPU and output caps, no host imports, network or filesystem); it cannot rewrite installed engine, auth or billing code.

## Run

Requires Python 3.11–3.14 and `uv`.

```bash
uv sync
export DAGI_API_KEY="..."
export DAGI_MODEL="gpt-4o-mini"
# For OpenRouter or another OpenAI-compatible endpoint:
# export DAGI_BASE_URL="https://openrouter.ai/api/v1"
# export DAGI_MODEL="provider/model"
uv run dagi
```

Environment variables:

- `DAGI_API_KEY` — required API key.
- `DAGI_BASE_URL` — API endpoint; defaults to `https://api.openai.com/v1`.
- `DAGI_MODEL` — model; defaults to `gpt-4o-mini`.
- `DAGI_MODEL_PRICES` — JSON model map with `input_per_million` and `output_per_million` prices in USD per million tokens. Without an entry for a model that was used, the run inspector reports the cost as unavailable (never as zero), names the unpriced models, and points here: a USD budget cannot be enforced for an unpriced model.
- `DAGI_MAX_PROVIDER_CALLS_PER_RUN` — maximum primary and auxiliary provider calls across the parent/child budget group; defaults to `32`. Game turns are additionally capped at `min(16, this value)`; the headroom exists so a learning contract can finish a skill iteration inside one turn, while budgets still bound total spend.
- `DAGI_BUDGET_USD` — optional shared parent/child spend limit; requires price entries for every selected model.
- `DAGI_ESTIMATE_MISSING_USAGE` — estimate missing token usage (default `true`); set to `false` to retain it as unavailable.
- `DAGI_CONTEXT_LIMIT_TOKENS` — approximate request-context limit; defaults to `32768`.
- `DAGI_CONTEXT_MAX_TOOL_RESULT_CHARS` — maximum tool-result characters sent in context; defaults to `4000`.
- `DAGI_COMPRESSION_MODEL` — history-compression model; defaults to `DAGI_MODEL` and can be priced separately.
- `DAGI_MAX_DELEGATION_DEPTH` — maximum nested child-agent depth; defaults to `2`.
- `DAGI_MAX_CHILD_AGENTS_PER_RUN` — maximum child agents across the shared budget group; defaults to `3`.
- `DAGI_GOAL_REPEAT_FAILURE_THRESHOLD` — cap goal retries and repeated identical known tool actions after this many fingerprints; defaults to `2`, range `1..10`.
- `DAGI_HOME` — database and skill storage; defaults to `~/.dagi`.
- `DAGI_WORKSPACE` — root for file tools; defaults to the current directory.
- `DAGI_ENABLE_SHELL=1` — enables shell execution with per-command approval in the CLI.
- `DAGI_ENABLE_CHECK_COMMANDS=1` — explicit operator opt-in for privileged goal command checks; defaults off and is never read from a request payload.
- `DAGI_WEB_HOST` / `DAGI_WEB_PORT` — sandbox bind address; defaults to `127.0.0.1:8765`.
- `DAGI_WEB_USERNAME` / `DAGI_WEB_PASSWORD_HASH` — login credentials; store a PBKDF2-SHA256 password hash, never a plaintext password.
- `DAGI_WEB_COOKIE_PATH` — session-cookie path; use `/dagi/` when mounted under that prefix.
- `DAGI_WEB_PUBLIC_ORIGIN` — exact HTTPS origin used to validate state-changing requests.
- `DAGI_WEB_COOKIE_SECURE` — marks the session cookie Secure; keep enabled behind HTTPS.
- `DAGI_WEB_TOKEN` — optional server-to-server Bearer credential; it is never sent to browser UI or returned by the API. Keep it in the protected service environment.
- `DAGI_WORKERS` — JSON object mapping worker names to `{"url":"https://worker.example","token":"<secret>"}`. Store tokens only in protected service configuration. Remote peers require HTTPS; plaintext HTTP is accepted only for loopback/SSH tunnels.

Authenticated worker routes are `GET /api/workers` and `/api/workers/<name>/proxy/<worker-api-path>`. The listing returns worker IDs and URLs only, never peer tokens; the proxy allowlists API paths and suppresses peer error bodies.

Budget checks happen between provider calls. A single provider response may exceed the configured budget before its final usage is available; missing usage is treated as unknown, never as zero. Context-compression calls are stored separately and count toward the same provider-call and budget limits.

## Agent delegation

The `delegate_task` tool accepts a required `task`, an optional `model`, and an optional `context` string. Each child has a distinct agent ID, session, and run. Parent history is not copied into a child; the child receives only the task and explicitly supplied context, and its memory search is limited to its own session. Child failures are returned to the parent as structured tool errors. The parent receives the result in its normal tool loop and is instructed to inspect and verify it before relying on it.

Depth and total child counts are bounded by `DAGI_MAX_DELEGATION_DEPTH` and `DAGI_MAX_CHILD_AGENTS_PER_RUN`. The root run has depth 0; at the default depth limit 2, agents at depth 2 cannot delegate further. The child cap counts all descendants in the shared budget group. Provider-call counts, usage, and configured USD budget are shared across the entire parent/child tree.

Example price configuration:

```bash
export DAGI_MODEL_PRICES='{"gpt-4o-mini":{"input_per_million":"0.15","output_per_million":"0.60"}}'
export DAGI_BUDGET_USD="0.25"
```

CLI commands: `/help`, `/new`, `/sessions`, `/resume <session_id>`, `/memory <query>`, `/skills`, `/model`, `/exit`. A run prints its ID and final status. Skills can be saved with `create_skill` and loaded with `use_skill`.

## Custom tools

Register tools through the public registry; duplicate names raise `ValueError`.

```python
from dagi_core.tools import Tool, ToolResult

registry.register(Tool(
    name="lookup_record",
    description="Look up a record by key.",
    parameters={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    handler=lambda args: ToolResult(f"record: {args['key']}"),
    retryable=True,  # Set only when repeating the operation is safe.
))
```

Handlers may return `ToolResult(content, is_error=True)` for a structured failure. A `verify_effect` callback returns `True` only when the effect is confirmed, `False` only when absence is confirmed, and `None` when the outcome remains unknown. Unknown non-retryable actions stay blocked during recovery.

## Verification

Full acceptance gate (run before closing an issue or release):

```bash
uv sync --extra dev
uv run python -m pytest -q
node --test tests/*ui.js
uv build
```

For faster issue-sized red/green feedback, run only the relevant pytest selectors and, when applicable, a focused Node UI pattern. The helper runs both checks concurrently and returns non-zero if either fails:

```bash
bash scripts/test-focused.sh \
  --node-pattern 'file update renderer shows bounded diffs' \
  tests/test_core_tools.py::test_write_file_returns_bounded_unified_diff_for_small_text_update \
  tests/test_core_tools.py::test_write_file_skips_diff_when_prior_file_exceeds_source_limit
```

Python-only example:

```bash
bash scripts/test-focused.sh tests/test_core_tools.py::test_read_file_returns_structured_path_size_line_count_and_truncation
```

Use the focused gate during small iterations; do not remove or weaken tests. Run the full acceptance gate once at the issue-closure checkpoint. Tests do not require an API key and do not make model requests. The workshop suites additionally execute real trials (Chipmunk physics and agent JavaScript), so they measure behavior instead of trusting claims.

## Layout

```text
dagi_core/agent.py     agent loop, run status, recovery, and usage budgets
dagi_core/provider.py  single OpenAI-compatible streaming adapter
dagi_core/tools.py     workspace files, memory, skills, optional shell
dagi_core/state.py     SQLite, FTS5, runs, requests, archives, and usage
dagi_core/context.py   bounded request assembly and history compression
dagi_core/usage.py     token provenance, model prices, and run limits
dagi_core/web.py       loopback web sandbox and HTTP API
dagi_core/static/      sandbox HTML and event-driven UI
dagi_core/config.py    environment-based configuration
dagi_core/cli.py       terminal interface
game/world.py          physical world: embodiment, objects, mechanics
game/rigid.py          Chipmunk rigid-body simulator
game/living.py         feedback policies and sensors
game/director.py       agent-owned JavaScript scene projects (quickjs)
game/embodiment.py     unassisted muscles, joint limits and appendages
game/mechanics.py      ropes, joints, springs, gears and materials
game/workshop.py       skill panel, controls and editable scenery
game/static/           canvas renderer, scene and workshop UI
docs/examples/         example recordings and the inline loops/storyboard
```

## Provenance

The first `main` commit (`b14b0ba`) was a prototype based on `Mohamedhasbini/hermes`; that snapshot and its MIT notice remain in Git history. The active implementation is a compact reimplementation informed by the current Hermes upstream commit [`848fc0a`](https://github.com/NousResearch/hermes-agent/commit/848fc0ad8be766b9dc10fe42bd80b5fc2d45d95c). See `NOTICE.md` for details.
