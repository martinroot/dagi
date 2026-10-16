import os
import stat

from dagi_core.state import StateStore


def test_session_messages_survive_reopen_and_keep_tool_call_pairing(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = StateStore(path)
    session = store.create_session("kernel")
    store.append_message(session, {"role": "user", "content": "write a file"})
    assistant = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "write_file", "arguments": '{"path":"a.txt"}'}}
        ],
    }
    store.append_message(session, assistant)
    store.append_message(session, {"role": "tool", "tool_call_id": "call-1", "name": "write_file", "content": "saved"})
    store.close()

    reopened = StateStore(path)
    assert reopened.messages(session) == [
        {"role": "user", "content": "write a file"},
        assistant,
        {"role": "tool", "tool_call_id": "call-1", "name": "write_file", "content": "saved"},
    ]
    reopened.close()


def test_full_text_search_is_literal_and_returns_session_context(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    first = store.create_session()
    second = store.create_session()
    store.append_message(first, {"role": "user", "content": 'ship with "quotes" and syntax'})
    store.append_message(second, {"role": "user", "content": "different topic"})

    hits = store.search_memory('"quotes" AND syntax')

    assert len(hits) == 1
    assert hits[0]["session_id"] == first
    assert hits[0]["role"] == "user"
    store.close()


def test_skills_can_be_created_loaded_and_listed(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")

    skill = store.create_skill(
        "release-check", "Verify a release", ["release", "tag"], "1. run tests\n2. tag"
    )

    assert store.get_skill("release-check")["body"].startswith("1. run tests")
    assert store.list_skills()[0]["name"] == skill["name"]
    store.close()


def test_run_statuses_are_persisted_and_terminal_outcomes_are_distinct(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    session = store.create_session()

    outcomes = {}
    for status in ("completed", "error", "limit", "cancelled"):
        run_id = store.create_run(session)
        assert store.get_run(run_id)["status"] == "running"
        store.finish_run(run_id, status)
        outcomes[status] = store.get_run(run_id)

    assert {run["status"] for run in outcomes.values()} == {
        "completed", "error", "limit", "cancelled"
    }
    assert all(run["session_id"] == session for run in outcomes.values())
    assert all(run["finished_at"] for run in outcomes.values())
    store.close()


def test_state_database_has_owner_only_permissions_on_posix(tmp_path):
    if os.name != "posix":
        return
    path = tmp_path / "private" / "state.sqlite3"
    store = StateStore(path)
    store.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
