import pytest

from dagi_core.state import StateStore


def test_child_session_lineage_workspace_and_inbox_survive_restart(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    parent_session = state.create_session("parent")
    parent_run = state.create_run(parent_session)
    child_session = state.create_session(
        "child", parent_id=parent_session, workspace=".dagi-children/child-1"
    )
    child_run = state.create_run(child_session, parent_run_id=parent_run, agent_name="child-model")
    state.append_message(child_session, {"role": "assistant", "content": "child result"})
    state.finish_run(child_run, "completed")
    state.notify_parent(child_session, child_run)
    state.close()

    reopened = StateStore(path)
    child = reopened.get_session(child_session)
    assert child is not None
    assert child["parent_id"] == parent_session
    assert child["workspace"] == ".dagi-children/child-1"
    assert reopened.children(parent_session)[0]["runs"][0]["parent_run_id"] == parent_run
    inbox = reopened.inbox(parent_session)
    assert inbox[0]["child_session_id"] == child_session
    assert inbox[0]["run_id"] == child_run
    assert inbox[0]["status"] == "completed"
    assert inbox[0]["result"] == "child result"
    assert inbox[0]["workspace"] == ".dagi-children/child-1"
    reopened.close()


def test_session_clone_copies_transcript_without_replaying_tool_effects(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    source = state.create_session("source", workspace="project")
    run = state.create_run(source)
    state.append_message(source, {"role": "user", "content": "make a file"})
    state.save_tool_round(
        source,
        run,
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "write-1", "type": "function", "function": {
                "name": "write_file", "arguments": '{"path":"result.txt","content":"ok"}',
            }},
        ]},
        [{"id": "write-1", "name": "write_file", "arguments": {"path": "result.txt", "content": "ok"}}],
    )
    state.mark_tool_call_running("write-1")
    state.append_message(source, {"role": "tool", "tool_call_id": "write-1", "name": "write_file", "content": "saved"})
    state.finish_tool_call("write-1", "succeeded", "saved")
    state.finish_run(run, "completed")

    clone = state.fork_session(source)

    assert clone != source
    assert [m["content"] for m in state.messages(clone)] == ["make a file", None, "saved"]
    assert state.list_tool_calls(clone) == []
    cloned = state.get_session(clone)
    assert cloned is not None and cloned["workspace"] == "project"
    state.close()


def test_session_workspace_must_be_relative_and_confined(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    parent = state.create_session("parent")
    for unsafe in ("/tmp/outside", "../outside", "child/../../escape"):
        with pytest.raises(ValueError, match="workspace"):
            state.create_session("child", parent_id=parent, workspace=unsafe)
    state.close()


def test_child_run_must_match_parent_session_lineage(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    parent_session = state.create_session("parent")
    parent_run = state.create_run(parent_session)
    unrelated_session = state.create_session("unrelated")
    with pytest.raises(ValueError, match="child session"):
        state.create_run(unrelated_session, parent_run_id=parent_run)
    state.close()


def test_child_run_cannot_start_after_parent_run_finishes(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    parent_session = state.create_session("parent")
    parent_run = state.create_run(parent_session)
    child_session = state.create_session("child", parent_id=parent_session)
    state.finish_run(parent_run, "completed")
    with pytest.raises(ValueError, match="parent run"):
        state.create_run(child_session, parent_run_id=parent_run)
    state.close()
