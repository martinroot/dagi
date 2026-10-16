"""Small environment-only configuration; secrets are never written to disk."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    home: Path
    workspace: Path
    enable_shell: bool

    @property
    def database(self) -> Path:
        return self.home / "state.sqlite3"


def load_config() -> Config:
    api_key = os.environ.get("DAGI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("DAGI_API_KEY is required; set it in the process environment")

    home_override = os.environ.get("DAGI_HOME")
    home = Path(home_override or "~/.dagi").expanduser().resolve()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Tighten only the app-owned default. An explicitly selected existing path
    # may be shared; the database itself is still owner-only.
    if os.name == "posix" and not home_override:
        os.chmod(home, 0o700)

    workspace = Path(os.environ.get("DAGI_WORKSPACE", Path.cwd())).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return Config(
        api_key=api_key,
        base_url=os.environ.get("DAGI_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/"),
        model=os.environ.get("DAGI_MODEL", DEFAULT_MODEL).strip(),
        home=home,
        workspace=workspace,
        enable_shell=_enabled(os.environ.get("DAGI_ENABLE_SHELL")),
    )
