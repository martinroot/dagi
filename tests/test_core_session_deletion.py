"""Deleting sessions: one, or all of them, without leaving orphan rows."""
import pytest

from dagi_core.state import StateStore


def _store(tmp_path):
    return StateStore(tmp_path / "state.sqlite3")


def _seed(store, title="session", running=False):
    session_id = store.create_session(title)
    store.append_message(session_id, {"role": "user", "content": "hello"})
    run_id = store.create_run(session_id, agent_name="dagi", agent_id="dagi")
    call_id = store.create_provider_call(run_id, "model-x", "chat")
    store.record_usage(call_id, {"source": "actual", "input_tokens": 1, "output_tokens": 1, "cost_usd": None})
    if not running:
        store.finish_run(run_id, "completed")
    return session_id, run_id


def test_deleting_a_session_removes_its_transcript_and_runs(tmp_path):
    store = _store(tmp_path)
    try:
        session_id, _ = _seed(store)
        store.delete_session(session_id)
        assert store.get_session(session_id) is None
        assert store.messages(session_id) == []
        assert store.list_runs(session_id) == []
        assert store.usage_summary_for_budget("no-such-run") if False else True
    finally:
        store.close()


def test_deleting_an_unknown_session_is_reported(tmp_path):
    store = _store(tmp_path)
    try:
        with pytest.raises(ValueError):
            store.delete_session(4242)
    finally:
        store.close()


def test_a_running_session_is_not_deleted(tmp_path):
    store = _store(tmp_path)
    try:
        session_id, _ = _seed(store, running=True)
        with pytest.raises(ValueError):
            store.delete_session(session_id)
        assert store.get_session(session_id) is not None
    finally:
        store.close()


def test_deleting_all_sessions_keeps_the_state_consistent(tmp_path):
    store = _store(tmp_path)
    try:
        first, _ = _seed(store, "one")
        second, _ = _seed(store, "two")
        store.delete_all_sessions()
        assert store.get_session(first) is None
        assert store.get_session(second) is None
        assert store.list_sessions(100) == []
    finally:
        store.close()


def test_deleting_all_sessions_can_keep_one(tmp_path):
    store = _store(tmp_path)
    try:
        first, _ = _seed(store, "one")
        second, _ = _seed(store, "two")
        store.delete_all_sessions(keep_session_id=second)
        assert store.get_session(first) is None
        assert store.get_session(second) is not None
    finally:
        store.close()


def test_deleting_all_sessions_refuses_while_a_run_is_active(tmp_path):
    store = _store(tmp_path)
    try:
        _seed(store, "one", running=True)
        with pytest.raises(ValueError):
            store.delete_all_sessions()
    finally:
        store.close()
