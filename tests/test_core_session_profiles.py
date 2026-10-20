"""A session carries the agent profile it was created from.

A Fabra agent is a package with its own brain and its own tool allow list.
Dagi kept one global system prompt and one global tool registry, so a cloned
agent ran as a generic Dagi agent. The session now stores the profile, and a
run uses the profile brain as the system prompt and exposes only the profile
tools to the model.
"""

import json

import pytest

from dagi_core.state import StateStore


@pytest.fixture()
def store(tmp_path):
    handle = StateStore(tmp_path / "state.sqlite3")
    try:
        yield handle
    finally:
        handle.close()


def test_session_without_profile_has_no_prompt_and_no_tools(store):
    session_id = store.create_session("plain")
    session = store.get_session(session_id)
    assert session["system_prompt"] == ""
    assert session["profile_tools"] == []
    assert session["profile"] == {}


def test_session_keeps_the_profile_it_was_created_with(store):
    session_id = store.create_session(
        "restorer",
        profile={"system_prompt": "You restore photos.", "tools": ["list_dir"]},
    )
    session = store.get_session(session_id)
    assert session["system_prompt"] == "You restore photos."
    assert session["profile_tools"] == ["list_dir"]


def test_profile_is_persisted_as_json(store):
    session_id = store.create_session(
        "restorer", profile={"system_prompt": "brain", "tools": ["a", "b"]}
    )
    row = store._db.execute(
        "SELECT profile_json FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    assert json.loads(row["profile_json"]) == {"system_prompt": "brain", "tools": ["a", "b"]}


def test_invalid_profile_is_rejected(store):
    with pytest.raises(ValueError):
        store.create_session("bad", profile="not a mapping")
    with pytest.raises(ValueError):
        store.create_session("bad", profile={"tools": "not a list"})
    with pytest.raises(ValueError):
        store.create_session("bad", profile={"tools": [1, 2]})
    with pytest.raises(ValueError):
        store.create_session("bad", profile={"system_prompt": "x" * 20000})


def test_cloning_a_template_carries_the_template_profile(store):
    template = store.create_template(
        "work-contract",
        task="fill the contract",
        brief="You are a contract agent.",
        tools=["document_template", "document_create"],
    )
    clone = store.clone_template(template["id"])
    session = store.get_session(clone["session_id"])
    assert session["system_prompt"] == "You are a contract agent."
    assert session["profile_tools"] == ["document_template", "document_create"]


def test_old_sessions_without_a_profile_column_still_load(tmp_path):
    """A database created before the profile column keeps working."""
    path = tmp_path / "legacy.sqlite3"
    handle = StateStore(path)
    try:
        handle._db.execute("ALTER TABLE sessions DROP COLUMN profile_json")
        handle._db.commit()
    except Exception:
        handle.close()
        raise
    handle.close()

    reopened = StateStore(path)
    try:
        session_id = reopened.create_session("legacy")
        session = reopened.get_session(session_id)
        assert session["system_prompt"] == ""
        assert session["profile_tools"] == []
    finally:
        reopened.close()
