"""The factory must survive a redeploy: its agents live in the repository."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dagi_core.factory_seed import BUILTIN_AGENTS, install_builtin_agents
from dagi_core.state import StateStore


def _store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state.sqlite3")


def test_the_built_in_agents_are_installed_into_an_empty_factory(tmp_path):
    store = _store(tmp_path)
    try:
        installed = install_builtin_agents(store)
        names = {item["name"] for item in store.list_templates()}
        assert "work-contract" in names
        assert "hermes-deploy" in names
        assert set(installed["templates"]) == names
        assert {skill["name"] for skill in store.list_skills()} >= {"work-contract"}
    finally:
        store.close()


def test_seeding_twice_does_not_duplicate_anything(tmp_path):
    store = _store(tmp_path)
    try:
        install_builtin_agents(store)
        first = len(store.list_templates()), len(store.list_skills())
        second_report = install_builtin_agents(store)
        assert second_report == {"templates": [], "skills": []}
        assert (len(store.list_templates()), len(store.list_skills())) == first
    finally:
        store.close()


def test_an_agent_the_operator_saved_is_never_overwritten(tmp_path):
    store = _store(tmp_path)
    try:
        store.create_template(
            "work-contract", task="my own contract flow", brief="my own brief"
        )
        store.create_skill("work-contract", "my own skill", ["mine"], "my own steps")
        install_builtin_agents(store)
        template = store.get_template_by_name("work-contract")
        assert template["task"] == "my own contract flow"
        assert template["brief"] == "my own brief"
        assert store.get_skill("work-contract")["description"] == "my own skill"
    finally:
        store.close()


def test_a_built_in_agent_declares_the_tools_it_needs(tmp_path):
    store = _store(tmp_path)
    try:
        install_builtin_agents(store)
        template = store.get_template_by_name("work-contract")
        assert "document_create" in template["tools"]
        assert "document_verify" in template["tools"]
        agent = next(item for item in BUILTIN_AGENTS if item["name"] == "work-contract")
        assert agent["task"].strip() and agent["brief"].strip()
    finally:
        store.close()


def test_a_built_in_agent_can_be_cloned_into_a_clean_session(tmp_path):
    store = _store(tmp_path)
    try:
        install_builtin_agents(store)
        template = store.get_template_by_name("work-contract")
        clone = store.clone_template(template["id"])
        session = store.get_session(clone["session_id"])
        assert session["brief"] == template["brief"]
        assert session["workspace"].startswith("sessions/")
        snapshot = store.session_snapshot(clone["session_id"])
        assert snapshot is not None and snapshot["messages"] == []
    finally:
        store.close()
