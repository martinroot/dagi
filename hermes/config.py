"""Small, environment-only configuration for the standalone Dagi core."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    home: Path
    workspace: Path
    enable_shell: bool

    @property
    def memory_db_path(self) -> Path:
        return self.home / "memory.sqlite3"

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"


def load_config() -> Config:
    api_key = os.environ.get("DAGI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("DAGI_API_KEY is required; set it in the process environment.")

    home = Path(os.environ.get("DAGI_HOME", "~/.dagi")).expanduser().resolve()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    skills_dir = home / "skills"
    skills_dir.mkdir(mode=0o700, exist_ok=True)
    if os.name == "posix":
        os.chmod(home, 0o700)
        os.chmod(skills_dir, 0o700)

    workspace = Path(os.environ.get("DAGI_WORKSPACE", Path.cwd())).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    return Config(
        api_key=api_key,
        base_url=os.environ.get("DAGI_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        model=os.environ.get("DAGI_MODEL", DEFAULT_MODEL),
        home=home,
        workspace=workspace,
        enable_shell=_env_bool("DAGI_ENABLE_SHELL", default=False),
    )
