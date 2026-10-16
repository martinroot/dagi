# Dagi Core — minimal Hermes-inspired agent

A compact terminal agent, not a reduced copy of the full Hermes platform. This implementation is aligned with the upstream `NousResearch/hermes-agent` architecture at commit [`848fc0a`](https://github.com/NousResearch/hermes-agent/commit/848fc0ad8be766b9dc10fe42bd80b5fc2d45d95c). The core is a clean implementation of selected invariants, not copied upstream source.

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
- Workspace-scoped file tools; a tool call is persisted before its side effect.
- A terminal CLI with session listing/resume and no web panel, gateway, or TUI framework.
- Interrupted tool actions are recovered by state: safe pending calls may resume, while unknown outcomes are never replayed automatically.

The runtime has one direct dependency, `openai`; SQLite and the CLI use the Python standard library. There is no web UI, messaging gateway, MCP, cron, voice, multi-agent, profile, or remote-backend integration in this version.

## Safety

`DAGI_ENABLE_SHELL` is disabled by default. When enabled, every shell command requires interactive approval; command text is escaped before display. The workspace constrains file tools but is not an OS-level sandbox for shell execution. The database is created with mode `0600`; the default `~/.dagi` directory is `0700` on POSIX. An explicitly selected existing `DAGI_HOME` keeps its existing directory permissions. The API key is read from the process environment and is not written to the repository or database.

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
- `DAGI_MODEL_PRICES` — JSON model map with `input_per_million` and `output_per_million` prices in USD per million tokens.
- `DAGI_MAX_PROVIDER_CALLS_PER_RUN` — maximum primary and auxiliary provider calls; defaults to `32`.
- `DAGI_BUDGET_USD` — optional per-run spend limit; requires a price entry for `DAGI_MODEL`.
- `DAGI_ESTIMATE_MISSING_USAGE` — estimate missing token usage (default `true`); set to `false` to retain it as unavailable.
- `DAGI_CONTEXT_LIMIT_TOKENS` — approximate request-context limit; defaults to `32768`.
- `DAGI_CONTEXT_MAX_TOOL_RESULT_CHARS` — maximum tool-result characters sent in context; defaults to `4000`.
- `DAGI_COMPRESSION_MODEL` — history-compression model; defaults to `DAGI_MODEL` and can be priced separately.
- `DAGI_HOME` — database and skill storage; defaults to `~/.dagi`.
- `DAGI_WORKSPACE` — root for file tools; defaults to the current directory.
- `DAGI_ENABLE_SHELL=1` — enables shell execution with per-command approval.

Budget checks happen between provider calls. A single provider response may exceed the configured budget before its final usage is available; missing usage is treated as unknown, never as zero. Context-compression calls are stored separately and count toward the same provider-call and budget limits.

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

```bash
uv sync --extra dev
uv run python -m pytest -q
uv build
```

Tests do not require an API key and do not make model requests.

## Layout

```text
dagi_core/agent.py     agent loop, run status, recovery, and usage budgets
dagi_core/provider.py  single OpenAI-compatible streaming adapter
dagi_core/tools.py     workspace files, memory, skills, optional shell
dagi_core/state.py     SQLite, FTS5, runs, requests, archives, and usage
dagi_core/context.py   bounded request assembly and history compression
dagi_core/usage.py     token provenance, model prices, and run limits
dagi_core/config.py    environment-based configuration
dagi_core/cli.py       terminal interface
```

## Provenance

The first `main` commit (`b14b0ba`) was a prototype based on `Mohamedhasbini/hermes`; that snapshot and its MIT notice remain in Git history. The active implementation is a compact reimplementation informed by the current Hermes upstream commit linked above. See `NOTICE.md` for details.
