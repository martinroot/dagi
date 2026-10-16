from pathlib import Path

from hermes.memory.store import MemoryStore


def test_memory_database_file_is_private(tmp_path: Path):
    import os
    import stat

    if os.name != "posix":
        return
    path = tmp_path / "memory.sqlite3"
    store = MemoryStore(path)
    store.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_session_and_message_roundtrip(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    session_id = store.create_session(title="test session")

    store.add_message(session_id, "user", "how do I deploy to railway?")
    store.add_message(session_id, "assistant", "run `railway up` from the project root")

    messages = store.get_messages(session_id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert "railway" in messages[0].content

    store.close()


def test_full_text_search_across_sessions(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    s1 = store.create_session()
    store.add_message(s1, "user", "the gunicorn worker keeps timing out on Railway")

    s2 = store.create_session()
    store.add_message(s2, "user", "what's the weather like today")

    hits = store.search("gunicorn")
    assert len(hits) == 1
    assert hits[0].session_id == s1

    store.close()


def test_search_tolerates_special_characters(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    session_id = store.create_session()
    store.add_message(session_id, "user", 'deploy with "quotes" AND weird -syntax')

    # This used to be a valid FTS5 boolean query; make sure it's treated as a
    # literal phrase instead of raising a malformed MATCH expression error.
    hits = store.search('"quotes" AND -syntax')
    assert isinstance(hits, list)

    store.close()


def test_list_sessions_orders_newest_first(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    first = store.create_session(title="first")
    second = store.create_session(title="second")

    sessions = store.list_sessions()
    assert sessions[0].id == second
    assert sessions[1].id == first

    store.close()


def test_session_summary(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    session_id = store.create_session()
    store.set_session_summary(session_id, "helped debug a deploy issue")

    sessions = store.list_sessions()
    assert sessions[0].summary == "helped debug a deploy issue"

    store.close()
