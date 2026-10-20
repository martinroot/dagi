"""Session templates: capture a working scenario and clone it as a clean run.

Dagi is a factory of agents: a template remembers the scenario and the tools
that made it work, and a clone starts a fresh session that inherits that
knowledge instead of a transcript.
"""
import pytest

from dagi_core.state import StateStore
from dagi_core.usage import UsagePolicy


def _store(tmp_path):
    return StateStore(tmp_path / "state.sqlite3")


def test_a_template_records_the_scenario_and_the_tools(tmp_path):
    store = _store(tmp_path)
    try:
        session_id = store.create_session("Hermes_ssh_tg")
        store.append_message(session_id, {"role": "user", "content": "Install the Hermes agent on a remote server, create a user and a token, and set up Telegram."})
        store.append_message(session_id, {"role": "assistant", "content": "Working on it."})
        store.create_skill("deploy-hermes", "Deploy Hermes to a remote host", ["deploy"], "1. read the key file 2. ssh ...")
        store.create_skill("telegram-link", "Bring the Telegram bot online", ["telegram"], "write the config, start the unit, send a message")

        template = store.create_template(
            "hermes-deploy",
            source_session_id=session_id,
            brief="Remote host, dedicated user, protected token, Telegram bot online.",
        )
        assert template["name"] == "hermes-deploy"
        assert "Install the Hermes agent" in template["task"]
        assert template["brief"].startswith("Remote host")
        assert sorted(template["skills"]) == ["deploy-hermes", "telegram-link"]
        assert template["source_session_id"] == session_id
    finally:
        store.close()


def test_cloning_a_template_yields_a_clean_session_with_the_scenario(tmp_path):
    store = _store(tmp_path)
    try:
        session_id = store.create_session("Hermes_ssh_tg")
        store.append_message(session_id, {"role": "user", "content": "Install Hermes and set up Telegram."})
        template = store.create_template("hermes-deploy", source_session_id=session_id, brief="Protected token, remote user, bot online.")

        clone = store.clone_template(template["id"])
        assert clone["session_id"] != session_id
        assert clone["task"].startswith("Install Hermes")
        assert clone["brief"] == "Protected token, remote user, bot online."

        fresh = store.get_session(clone["session_id"])
        assert fresh is not None
        assert fresh["title"]
        assert fresh["brief"] == "Protected token, remote user, bot online."
        assert store.messages(clone["session_id"]) == [], "a clone starts with no transcript"
        assert store.list_runs(clone["session_id"]) == [], "a clone starts with no runs"
        assert store.get_session(session_id) is not None, "the source session survives cloning"
    finally:
        store.close()


def test_templates_are_listed_and_deleted(tmp_path):
    store = _store(tmp_path)
    try:
        session_id = store.create_session("first")
        store.append_message(session_id, {"role": "user", "content": "do the thing"})
        first = store.create_template("alpha", source_session_id=session_id)
        store.create_template("beta", source_session_id=session_id, task="another task")
        names = [item["name"] for item in store.list_templates()]
        assert "alpha" in names and "beta" in names
        store.delete_template(first["id"])
        assert "alpha" not in [item["name"] for item in store.list_templates()]
    finally:
        store.close()


def test_a_template_needs_a_name_and_a_task(tmp_path):
    store = _store(tmp_path)
    try:
        session_id = store.create_session("first")
        with pytest.raises(ValueError):
            store.create_template("", source_session_id=session_id)
        with pytest.raises(ValueError):
            store.create_template("alpha", source_session_id=session_id, task="   ")
    finally:
        store.close()


def test_a_session_brief_reaches_the_agent_runtime_context(tmp_path):
    from dagi_core.runtime_context import build_runtime_context

    store = _store(tmp_path)
    try:
        session_id = store.create_session("clone", brief="Deploy Hermes, then link Telegram.")
        session = store.get_session(session_id)
        context = build_runtime_context(
            agent_id="dagi",
            agent_name="dagi",
            session=session,
            run={"run_id": "r1", "status": "running", "depth": 0, "agent_name": "dagi"},
            entry_point="web",
            resolved_workspace=".",
            enabled_tools=["read_file", "write_file"],
            user_message_id=1,
            usage_summary={"provider_calls": 0, "cost_usd": None},
            usage_policy=UsagePolicy(),
        )
        assert context["scenario_brief"] == "Deploy Hermes, then link Telegram."
    finally:
        store.close()
