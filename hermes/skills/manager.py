"""CRUD + search over the skill library on disk.

This is the "procedural memory" half of the learning loop: skills are
created from completed tasks, refined as they're reused, and searched by
name/description/trigger keywords so the agent can pull one into context
before attempting a task it's solved before.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .schema import Skill


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "skill"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillManager:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, name: str) -> Path:
        return self.skills_dir / f"{_slugify(name)}.md"

    def create_skill(
        self,
        name: str,
        description: str,
        body: str,
        triggers: list[str] | None = None,
        source_session: int | None = None,
    ) -> Skill:
        path = self._path_for(name)
        if path.exists():
            raise FileExistsError(f"Skill {name!r} already exists at {path}")
        skill = Skill(
            name=name,
            description=description,
            triggers=triggers or [],
            body=body,
            created_at=_now(),
            source_session=source_session,
        )
        path.write_text(skill.to_markdown(), encoding="utf-8")
        return skill

    def get_skill(self, name: str) -> Skill | None:
        path = self._path_for(name)
        if not path.exists():
            return None
        return Skill.from_markdown(path.read_text(encoding="utf-8"))

    def list_skills(self) -> list[Skill]:
        skills = []
        for path in sorted(self.skills_dir.glob("*.md")):
            try:
                skills.append(Skill.from_markdown(path.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return sorted(skills, key=lambda s: s.use_count, reverse=True)

    def search(self, query: str) -> list[Skill]:
        q = query.lower()
        hits = []
        for skill in self.list_skills():
            haystack = " ".join([skill.name, skill.description, *skill.triggers]).lower()
            if q in haystack:
                hits.append(skill)
        return hits

    def record_use(self, name: str) -> Skill | None:
        skill = self.get_skill(name)
        if skill is None:
            return None
        skill.use_count += 1
        skill.last_used_at = _now()
        self._path_for(name).write_text(skill.to_markdown(), encoding="utf-8")
        return skill

    def refine_skill(
        self,
        name: str,
        new_body: str | None = None,
        new_description: str | None = None,
        new_triggers: list[str] | None = None,
    ) -> Skill:
        skill = self.get_skill(name)
        if skill is None:
            raise KeyError(f"No such skill: {name!r}")
        if new_body is not None:
            skill.body = new_body
        if new_description is not None:
            skill.description = new_description
        if new_triggers is not None:
            skill.triggers = new_triggers
        skill.version += 1
        self._path_for(name).write_text(skill.to_markdown(), encoding="utf-8")
        return skill

    def delete_skill(self, name: str) -> bool:
        path = self._path_for(name)
        if path.exists():
            path.unlink()
            return True
        return False
