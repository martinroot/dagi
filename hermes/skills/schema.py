"""Skill file format: YAML frontmatter + a markdown procedure body.

Compatible in spirit with the agentskills.io convention -- a skill is a
plain markdown file an agent (or a human) can read directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    version: int = 1
    use_count: int = 0
    created_at: str = ""
    last_used_at: str | None = None
    source_session: int | None = None

    def to_markdown(self) -> str:
        frontmatter = yaml.safe_dump(
            {
                "name": self.name,
                "description": self.description,
                "triggers": self.triggers,
                "version": self.version,
                "use_count": self.use_count,
                "created_at": self.created_at,
                "last_used_at": self.last_used_at,
                "source_session": self.source_session,
            },
            sort_keys=False,
        )
        return f"---\n{frontmatter}---\n{self.body.strip()}\n"

    @classmethod
    def from_markdown(cls, text: str) -> "Skill":
        match = FRONTMATTER_RE.match(text)
        if not match:
            raise ValueError("Skill file is missing YAML frontmatter")
        meta = yaml.safe_load(match.group(1)) or {}
        body = match.group(2).strip()
        return cls(
            name=meta["name"],
            description=meta.get("description", ""),
            triggers=meta.get("triggers") or [],
            body=body,
            version=meta.get("version", 1),
            use_count=meta.get("use_count", 0),
            created_at=meta.get("created_at", ""),
            last_used_at=meta.get("last_used_at"),
            source_session=meta.get("source_session"),
        )
