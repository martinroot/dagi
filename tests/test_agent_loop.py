from pathlib import Path

from hermes.agent.loop import AgentLoop
from hermes.agent.tools import ToolRegistry
from hermes.memory.store import MemoryStore
from hermes.providers.base import StreamChunk, ToolCall
from hermes.skills.manager import SkillManager


class FakeProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def stream(self, system, messages, tools):
        self.calls += 1
        return iter(self.responses.pop(0))


def test_agent_loop_executes_tool_then_returns_final_response(tmp_path: Path):
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    skills = SkillManager(tmp_path / "skills")
    session_id = memory.create_session()
    tools = ToolRegistry(tmp_path, memory, skills, session_id)
    provider = FakeProvider(
        [
            StreamChunk(
                kind="tool_call",
                tool_call=ToolCall(
                    id="call-1",
                    name="write_file",
                    arguments={"path": "notes.txt", "content": "created by the core"},
                ),
            )
        ],
        [StreamChunk(kind="text_delta", text="File saved.")],
    )
    loop = AgentLoop(provider, tools, memory, skills, session_id)

    events = list(loop.run_turn("Save a note"))

    assert (tmp_path / "notes.txt").read_text() == "created by the core"
    assert provider.calls == 2
    assert any(event.kind == "tool_result" and "wrote" in (event.text or "") for event in events)
    assert any(event.kind == "text" and event.text == "File saved." for event in events)
    assert events[-1].kind == "done"
    assert [message.role for message in memory.get_messages(session_id)] == ["user", "tool", "assistant"]
    memory.close()
