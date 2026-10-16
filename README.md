# Dagi Core — minimal Hermes-inspired agent

A compact terminal agent, not a reduced copy of the full Hermes platform. This implementation is aligned with the upstream `NousResearch/hermes-agent` architecture at commit [`848fc0a`](https://github.com/NousResearch/hermes-agent/commit/848fc0ad8be766b9dc10fe42bd80b5fc2d45d95c). The core is a clean implementation of selected invariants, not copied upstream source.

## Core features

- One streaming OpenAI-compatible API adapter.
- An agent loop for text, tool calls, tool results, and follow-up responses.
- SQLite transcript, FTS5 memory search, and persistent reusable skills.
- Durable run records with `completed`, `error`, `limit`, and `cancelled` outcomes.
- Events correlated by session ID, run ID, and tool-call ID.
- Workspace-scoped file tools; a tool call is persisted before its side effect.
- A terminal CLI with no web panel, gateway, or TUI framework.

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
- `DAGI_HOME` — database and skill storage; defaults to `~/.dagi`.
- `DAGI_WORKSPACE` — root for file tools; defaults to the current directory.
- `DAGI_ENABLE_SHELL=1` — enables shell execution with per-command approval.

CLI commands: `/help`, `/new`, `/memory <query>`, `/skills`, `/model`, `/exit`. A run prints its ID and final status. Skills can be saved with `create_skill` and loaded with `use_skill`.

## Verification

```bash
uv sync --extra dev
uv run python -m pytest -q
uv build
```

Tests do not require an API key and do not make model requests.

## Layout

```text
dagi_core/agent.py     agent loop, run status, durable tool-call ordering
dagi_core/provider.py  single OpenAI-compatible streaming adapter
dagi_core/tools.py     workspace files, memory, skills, optional shell
dagi_core/state.py     SQLite, FTS5, sessions, runs, and skills
dagi_core/config.py    environment-based configuration
dagi_core/cli.py       terminal interface
```

## Provenance

The first `main` commit (`b14b0ba`) was a prototype based on `Mohamedhasbini/hermes`; that snapshot and its MIT notice remain in Git history. The active implementation is a compact reimplementation informed by the current Hermes upstream commit linked above. See `NOTICE.md` for details.
