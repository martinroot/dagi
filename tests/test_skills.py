from pathlib import Path

import pytest

from hermes.skills.manager import SkillManager


def test_create_and_get_skill(tmp_path: Path):
    mgr = SkillManager(tmp_path / "skills")
    mgr.create_skill(
        name="Deploy Flask to Railway",
        description="Deploy a Flask app to Railway",
        body="1. railway login\n2. railway up",
        triggers=["railway", "deploy"],
    )

    skill = mgr.get_skill("Deploy Flask to Railway")
    assert skill is not None
    assert skill.description == "Deploy a Flask app to Railway"
    assert "railway up" in skill.body
    assert skill.use_count == 0
    assert skill.version == 1


def test_duplicate_skill_name_raises(tmp_path: Path):
    mgr = SkillManager(tmp_path / "skills")
    mgr.create_skill(name="dup", description="d", body="b")
    with pytest.raises(FileExistsError):
        mgr.create_skill(name="dup", description="d2", body="b2")


def test_record_use_increments_and_stamps(tmp_path: Path):
    mgr = SkillManager(tmp_path / "skills")
    mgr.create_skill(name="dup", description="d", body="b")

    mgr.record_use("dup")
    mgr.record_use("dup")

    skill = mgr.get_skill("dup")
    assert skill.use_count == 2
    assert skill.last_used_at is not None


def test_refine_skill_bumps_version(tmp_path: Path):
    mgr = SkillManager(tmp_path / "skills")
    mgr.create_skill(name="dup", description="d", body="b")

    mgr.refine_skill("dup", new_body="better body", new_description="better desc")

    skill = mgr.get_skill("dup")
    assert skill.version == 2
    assert skill.body == "better body"
    assert skill.description == "better desc"


def test_search_matches_name_description_and_triggers(tmp_path: Path):
    mgr = SkillManager(tmp_path / "skills")
    mgr.create_skill(
        name="railway-deploy",
        description="ship a flask app",
        body="...",
        triggers=["gunicorn", "procfile"],
    )
    mgr.create_skill(name="unrelated", description="something else entirely", body="...")

    assert [s.name for s in mgr.search("gunicorn")] == ["railway-deploy"]
    assert [s.name for s in mgr.search("flask")] == ["railway-deploy"]
    assert [s.name for s in mgr.search("nonexistent")] == []


def test_list_skills_sorted_by_use_count(tmp_path: Path):
    mgr = SkillManager(tmp_path / "skills")
    mgr.create_skill(name="a", description="d", body="b")
    mgr.create_skill(name="b", description="d", body="b")

    mgr.record_use("b")
    mgr.record_use("b")
    mgr.record_use("a")

    names = [s.name for s in mgr.list_skills()]
    assert names[0] == "b"
