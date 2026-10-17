"""The only surface in the minimal core: a small terminal REPL."""

from __future__ import annotations

import sys

from .agent import Agent
from .config import load_config
from .context import ContextBuilder
from .delegation import DelegationManager
from .provider import OpenAICompatibleProvider
from .state import StateStore
from .tools import ToolRegistry

HELP = """Commands:
  /help                 show commands
  /new                  start a fresh session
  /sessions             list saved sessions
  /resume <session_id>  resume a saved session
  /memory <query>       search saved messages
  /skills               list saved procedures
  /model                show the configured model and endpoint
  /exit                 quit
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


def _new_agent(config, provider, state, session_id: int | None = None) -> Agent:
    def tools_for(active_session_id: int) -> ToolRegistry:
        tools = ToolRegistry(
            config.workspace,
            state,
            active_session_id,
            shell_enabled=config.enable_shell,
            approve_shell=approve_shell_command if config.enable_shell else None,
        )
        delegation = DelegationManager(
            state,
            config.workspace,
            api_key=config.api_key,
            base_url=config.base_url,
            usage_policy=config.usage_policy,
            compression_model=config.compression_model,
            context_limit_tokens=config.context_limit_tokens,
            context_max_tool_result_chars=config.context_max_tool_result_chars,
            max_depth=config.max_delegation_depth,
            max_children=config.max_child_agents_per_run,
            shell_enabled=config.enable_shell,
            approve_shell=approve_shell_command if config.enable_shell else None,
        )
        delegation.register(tools)
        return tools

    compressor = OpenAICompatibleProvider(config.compression_model, config.api_key, config.base_url)
    context_builder = ContextBuilder(
        state,
        max_tokens=config.context_limit_tokens,
        max_tool_result_chars=config.context_max_tool_result_chars,
        compression_provider=compressor,
        usage_policy=config.usage_policy,
    )
    return Agent(
        provider, tools_for, state, session_id,
        usage_policy=config.usage_policy,
        context_builder=context_builder,
    )


def run() -> None:
    config = load_config()
    state = StateStore(config.database)
    provider = OpenAICompatibleProvider(config.model, config.api_key, config.base_url)
    session_id = state.create_session()
    agent = _new_agent(config, provider, state)
    print(f"Dagi Core | {config.model} | session: {session_id} | workspace: {config.workspace}")
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
                    session_id = state.create_session()
                    print(f"Started a new session: {session_id}.")
                elif command == "/sessions":
                    sessions = state.list_sessions()
                    print("\n".join(
                        f"{item['id']}: {item['title'] or 'untitled'} ({item['created_at']})"
                        for item in sessions
                    ) or "(no sessions)")
                elif command == "/resume" and argument:
                    try:
                        session_id = int(argument)
                    except ValueError:
                        print("Usage: /resume <session_id>")
                    else:
                        known = {item["id"] for item in state.list_sessions(100)}
                        if session_id not in known:
                            print(f"No saved session {session_id}.")
                        else:
                            calls = state.recover_interrupted(session_id)
                            pending = sum(call["status"] == "pending" for call in calls)
                            uncertain = sum(call["status"] == "uncertain" for call in calls)
                            print(f"Resumed session {session_id}; pending tools: {pending}, uncertain tools: {uncertain}.")
                elif command == "/model":
                    print(f"{config.model} ({config.base_url})")
                elif command == "/skills":
                    skills = state.list_skills()
                    print("\n".join(f"- {skill['name']}: {skill['description']}" for skill in skills) or "(no skills yet)")
                elif command == "/memory" and argument:
                    hits = state.search_memory(argument)
                    print("\n".join(f"[session {hit['session_id']}, {hit['role']}] {hit['snippet']}" for hit in hits) or "(no matches)")
                else:
                    print("Usage: /help, /new, /sessions, /resume <session_id>, /memory <query>, /skills, /model, /exit")
                continue

            for event in agent.run_turn(text, session_id=session_id):
                if event.kind == "text" and event.text:
                    print(event.text, end="", flush=True)
                elif event.kind == "tool_call":
                    print(f"\n-> [{event.run_id}/{event.tool_call_id}] {event.tool_name}({event.tool_args!r})")
                elif event.kind == "tool_result":
                    print((event.text or "")[:400])
                elif event.kind == "error":
                    print(f"\nError: {event.text}", file=sys.stderr)
                elif event.kind == "done":
                    print(f"\n[{event.run_id}] {event.status}")
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
