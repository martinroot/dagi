"""The only surface in the minimal core: a small terminal REPL."""

from __future__ import annotations

import sys

from .agent import Agent
from .config import load_config
from .provider import OpenAICompatibleProvider
from .state import StateStore
from .tools import ToolRegistry

HELP = """Commands:
  /help            show commands
  /new             start a fresh session
  /memory <query>  search saved messages
  /skills          list saved procedures
  /model           show the configured model and endpoint
  /exit            quit
"""


def approve_shell_command(command: str) -> bool:
    """Show the exact command safely and default to no unless explicitly approved."""
    print("\n[approval required] The model requested this shell command:")
    print(f"  {command!r}")
    try:
        answer = input("Run it? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


def _new_agent(config, provider, state) -> Agent:
    session_id = state.create_session()
    tools = ToolRegistry(
        config.workspace,
        state,
        session_id,
        shell_enabled=config.enable_shell,
        approve_shell=approve_shell_command if config.enable_shell else None,
    )
    return Agent(provider, tools, state, session_id)


def run() -> None:
    config = load_config()
    state = StateStore(config.database)
    provider = OpenAICompatibleProvider(config.model, config.api_key, config.base_url)
    agent = _new_agent(config, provider, state)
    print(f"Dagi Core | {config.model} | workspace: {config.workspace}")
    print("Type /help. Shell is disabled unless DAGI_ENABLE_SHELL=1.\n")

    try:
        while True:
            try:
                text = input("dagi> ")
            except (EOFError, KeyboardInterrupt):
                break
            if not text.strip():
                continue
            if text.startswith("/"):
                command, _, argument = text.strip().partition(" ")
                if command == "/exit":
                    break
                if command == "/help":
                    print(HELP)
                elif command == "/new":
                    agent = _new_agent(config, provider, state)
                    print("Started a new session.")
                elif command == "/model":
                    print(f"{config.model} ({config.base_url})")
                elif command == "/skills":
                    skills = state.list_skills()
                    print("\n".join(f"- {skill['name']}: {skill['description']}" for skill in skills) or "(no skills yet)")
                elif command == "/memory" and argument:
                    hits = state.search_memory(argument)
                    print("\n".join(f"[session {hit['session_id']}, {hit['role']}] {hit['snippet']}" for hit in hits) or "(no matches)")
                else:
                    print("Usage: /help, /new, /memory <query>, /skills, /model, /exit")
                continue

            for event in agent.run_turn(text):
                if event.kind == "text" and event.text:
                    print(event.text, end="", flush=True)
                elif event.kind == "tool_call":
                    print(f"\n-> {event.tool_name}({event.tool_args!r})")
                elif event.kind == "tool_result":
                    print((event.text or "")[:400])
                elif event.kind == "error":
                    print(f"\nError: {event.text}", file=sys.stderr)
                elif event.kind == "done":
                    print()
    finally:
        state.close()
        print("\nSession saved.")


def main() -> None:
    try:
        run()
    except ValueError as exc:
        print(f"dagi: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
