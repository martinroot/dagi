"""The learning loop: turn a finished conversation into a session summary
and, if the task was non-trivial, a new (or refined) skill.
"""

from __future__ import annotations

import re

from hermes.providers.base import LLMProvider, Message
from hermes.skills.manager import SkillManager

from hermes.agent.prompts import SESSION_SUMMARY_PROMPT, SKILL_AUTHORING_PROMPT

_SKILL_FIELD_RE = re.compile(
    r"NAME:\s*(?P<name>.+?)\s*\n"
    r"DESCRIPTION:\s*(?P<description>.+?)\s*\n"
    r"TRIGGERS:\s*(?P<triggers>.*?)\s*\n"
    r"BODY:\s*\n(?P<body>.*)",
    re.DOTALL,
)


def render_transcript(turns: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"[{role}]\n{content}" for role, content in turns)


def _complete(provider: LLMProvider, prompt: str) -> str:
    parts: list[str] = []
    for chunk in provider.stream(
        system="", messages=[Message(role="user", content=prompt)], tools=[]
    ):
        if chunk.kind == "text_delta" and chunk.text:
            parts.append(chunk.text)
    return "".join(parts).strip()


def summarize_session(provider: LLMProvider, turns: list[tuple[str, str]]) -> str:
    transcript = render_transcript(turns)
    return _complete(provider, SESSION_SUMMARY_PROMPT.format(transcript=transcript))


def propose_skill(
    provider: LLMProvider,
    skills: SkillManager,
    turns: list[tuple[str, str]],
    session_id: int,
) -> str | None:
    """Ask the model to distill the session into a skill and save it.

    Returns the skill's name if one was created or refined, None if the
    model judged nothing here was worth keeping.
    """
    transcript = render_transcript(turns)
    response = _complete(provider, SKILL_AUTHORING_PROMPT.format(transcript=transcript))

    if response.strip().upper() == "NONE":
        return None

    match = _SKILL_FIELD_RE.search(response)
    if not match:
        return None

    name = match.group("name").strip()
    description = match.group("description").strip()
    triggers = [t.strip() for t in match.group("triggers").split(",") if t.strip()]
    body = match.group("body").strip()

    if skills.get_skill(name) is not None:
        skills.refine_skill(
            name, new_body=body, new_description=description, new_triggers=triggers
        )
    else:
        skills.create_skill(
            name=name,
            description=description,
            body=body,
            triggers=triggers,
            source_session=session_id,
        )
    return name
