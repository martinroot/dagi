# Fabra → Dagi migration

Fabra and Dagi share one agent model. A Fabra agent is a package: a brain, a
tool allow list, a task and a set of inputs. Dagi is the agent core: the
model loop, the tools, the transcript, the workspace and the cost accounting.
This file is the status map for moving the Fabra catalogue onto the Dagi core
without breaking the live portal.

Rule of the cycle: one agent at a time. Its dialogue, its streaming and its
tools are tested inside the Dagi core; the fixes land in the core, not in the
agent package; only an agent that passes is shipped to the site.

## Where the pieces live

| Piece | Path |
|---|---|
| Fabra agent packages (source of truth) | `/var/www/fabra/data/agents/<slug>/agent.yaml` |
| Fabra test registry (probe input per agent) | `/var/www/fabra/data/agent-test-registry.json` |
| Dagi core (repository) | `/home/main/dagi` → `github.com/martinroot/dagi` |
| Dagi runtime on the server | `/var/www/fabra/dagi`, service `dagi-web.service` |
| Dagi state database | `/var/www/fabra/data/dagi/state.sqlite3` |
| Debug console (sessions, money, catalogue) | `https://fabra.live/dagi/` |
| Fabra sandbox clone (card, master, chat) | `https://fabra.live/dagi/fabra/` |
| Upstream Dagi sandbox (repository UI) | `https://fabra.live/dagi/sandbox/` |
| Export script (Fabra packages → Dagi templates) | `/home/main/dagi-deploy/export_fabra_agents_to_dagi.py` |
| Test runner (one agent at a time) | `/home/main/dagi-deploy/run_agent_migration_tests.py` |
| Machine report of the last run | `/var/www/fabra/data/dagi/migration-report.json` |

## Fabra tool names and their Dagi counterparts

| Fabra | Dagi | Note |
|---|---|---|
| `files.list` | `list_dir` | |
| `files.read` | `read_file` | |
| `files.write` | `write_file` | |
| `document.template` | `document_template` | |
| `document.read_input` | `document_read` | |
| `document.latest` | `document_latest` | |
| `document.create_docx` | `document_create` | |
| `document.edit` | `document_edit` | |
| `document.verify` | `document_verify` | |
| `search_memory` | `search_memory` | |

Not in the Dagi core yet: `image.edit`, `image.generate`, `image.merge_prompt`,
`image.edit_batch`, `music.generate`, `video.generate`, `video.export`,
`audio.transcribe`, `audio.synthesize`, `artifact.publish`. An agent that needs
one of them is reported with the gap instead of silently losing the tool.

## Task board

| ID | Task | Status | Evidence |
|---|---|---|---|
| FGM-01 | Rebuild the sandbox left navigation | Done | `cbea1b4`; 241 tests |
| FGM-02 | Export the Fabra catalogue into the Dagi core as templates and skills | Done | 32 packages → 33 templates, 33 skills |
| FGM-03 | A session runs the agent profile it was created from | Done | `07b8755`; profile brain and tool allow list |
| FGM-04 | Debug console with sessions, transcripts, templates, runs and money | Done | `https://fabra.live/dagi/` |
| FGM-05 | Fabra catalogue tab in the console, with a one click import | Done | 32 cards, gap report per card |
| FGM-06 | Fabra sandbox clone: card, master form, chat on the Dagi core | Done | `https://fabra.live/dagi/fabra/` |
| FGM-07 | Test runner: dialogue, streaming, tools, cost per agent | Done | 30/31 pass, 1 stale registry entry |
| FGM-08 | Streaming transport in the clone: server sent events instead of polling | Open | the clone polls the transcript |
| FGM-09 | Media tools in the core: image, music, video, audio, artifact publish | Open | 24 agents report a tool gap |
| FGM-10 | Ship the passed agents to the site: route the Fabra chat to the Dagi core | Open | needs a routing decision per agent |
| FGM-11 | Remove the stale `ssh-vless-vpn` entry from the Fabra test registry | Open | no package, no row in `agents` |

## Core changes made for the migration

- **Agent profile.** A session stores the profile it was created from. A run
  uses the profile brain as the system prompt and offers the model only the
  profile tools. Before this, every agent ran as a generic Dagi agent: its own
  brain was ignored and the model was offered the whole registry.
- **Tool restriction.** `ToolRegistry.restrict_to(names)` narrows what the
  model is offered. Unknown names are ignored, and a profile that matches
  nothing leaves the full registry visible instead of leaving the model with
  no tools at all.

## Rules for shipping an agent

An agent may go to the site when all of the following hold:

1. The test runner reports `PASS` for it: the session was created, the run
   finished, the agent answered, and it called no tool outside its profile.
2. The agent has no tool gap, or the gap is closed in the core first.
3. Its Fabra package and the Dagi template describe the same brain and the
   same tool allow list.
4. The cost of the probe run is recorded, so the site price still covers the
   model call.
