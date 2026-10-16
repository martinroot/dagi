"""Small standard-library REPL for the core agent loop."""

from __future__ import annotations

import sys

from hermes.agent.loop import AgentLoop
from hermes.agent.tools import ToolRegistry
from hermes.config import load_config
from hermes.learning import curator
from hermes.memory.store import MemoryStore
from hermes.providers.registry import get_provider
from hermes.skills.manager import SkillManager

HELP_TEXT = """Commands:
  /help            show this message
  /skills          list saved skills
  /memory <query>  search past conversations
  /new             start a new session
  /learn           extract a reusable skill from this session
  /model           show the active model and endpoint
  /exit            quit
"""


class DagiCLI:
    def __init__(self) -> None:
        self.config = load_config()
        self.provider = get_provider(self.config)
        self.memory = MemoryStore(self.config.memory_db_path)
        self.skills = SkillManager(self.config.skills_dir)
        self.loop = self._new_loop()

    def _new_loop(self) -> AgentLoop:
        session_id = self.memory.create_session()
        tools = ToolRegistry(
            workspace=self.config.workspace,
            memory=self.memory,
            skills=self.skills,
            session_id=session_id,
            enable_shell=self.config.enable_shell,
            approve_shell=self._approve_shell if self.config.enable_shell else None,
        )
        return AgentLoop(self.provider, tools, self.memory, self.skills, session_id)

    @staticmethod
    def _approve_shell(command: str) -> bool:
        print("\n[approval required] The model requested this shell command:")
        print(f"  {command!r}")
        try:
            answer = input("Run it? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() in {"y", "yes"}

    def run(self) -> None:
        print(f"dagi core -- {self.config.model} -- workspace {self.config.workspace}")
        print("Type /help for commands; shell access is off unless DAGI_ENABLE_SHELL=1.\n")
        try:
            while True:
                try:
                    user_input = input("dagi> ")
                except (EOFError, KeyboardInterrupt):
                    break
                if not user_input.strip():
                    continue
                if user_input.startswith("/"):
                    if self._handle_command(user_input):
                        break
                else:
                    self._run_turn(user_input)
        finally:
            self.loop.close_session()
            self.memory.close()
            print("\nSession saved.")

    def _handle_command(self, raw: str) -> bool:
        parts = raw.strip().split(maxsplit=1)
        command = parts[0]
        argument = parts[1] if len(parts) > 1 else ""

        if command == "/exit":
            return True
        if command == "/help":
            print(HELP_TEXT)
        elif command == "/model":
            print(f"{self.config.model} ({self.config.base_url})")
        elif command == "/skills":
            skills = self.skills.list_skills()
            if not skills:
                print("(no skills yet)")
            for skill in skills:
                print(f"- {skill.name} (used {skill.use_count}x): {skill.description}")
        elif command == "/memory":
            if not argument:
                print("Usage: /memory <query>")
            else:
                hits = self.memory.search(argument)
                if not hits:
                    print("(no matches)")
                for hit in hits:
                    print(f"[session {hit.session_id}, {hit.role}] {hit.snippet}")
        elif command == "/new":
            self.loop.close_session()
            self.loop = self._new_loop()
            print("Started a new session.")
        elif command == "/learn":
            if not self.loop.turn_log:
                print("(nothing to learn from yet)")
            else:
                try:
                    name = curator.propose_skill(
                        self.provider, self.skills, self.loop.turn_log, self.loop.session_id
                    )
                    print(f"Saved skill: {name}" if name else "(nothing reusable found)")
                except Exception as exc:
                    print(f"Learning failed: {exc}", file=sys.stderr)
        else:
            print(f"Unknown command: {command}")
        return False

    def _run_turn(self, user_input: str) -> None:
        for event in self.loop.run_turn(user_input):
            if event.kind == "text" and event.text:
                print(event.text, end="", flush=True)
            elif event.kind == "tool_call":
                print(f"\n-> {event.tool_name}({event.tool_args})")
            elif event.kind == "tool_result":
                preview = (event.text or "")[:400]
                print(preview)
            elif event.kind == "skill_created":
                print(f"\nLearned a skill: {event.tool_name}")
            elif event.kind == "error":
                print(f"\nError: {event.text}", file=sys.stderr)
            elif event.kind == "done":
                print()


def main() -> None:
    try:
        DagiCLI().run()
    except ValueError as exc:
        print(f"dagi: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
