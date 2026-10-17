"""Small environment-only configuration; secrets are never written to disk."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .usage import ModelPrice, UsagePolicy

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
    usage_policy: UsagePolicy
    compression_model: str
    context_limit_tokens: int
    context_max_tool_result_chars: int
    max_delegation_depth: int
    max_child_agents_per_run: int
    web_username: str = ""
    web_password_hash: str = ""
    web_cookie_path: str = "/"
    web_public_origin: str = ""
    web_cookie_secure: bool = True

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
    model = os.environ.get("DAGI_MODEL", DEFAULT_MODEL).strip()
    try:
        raw_prices = json.loads(os.environ.get("DAGI_MODEL_PRICES", "{}"))
        if not isinstance(raw_prices, dict):
            raise ValueError("DAGI_MODEL_PRICES must be a JSON object")
        prices = {
            name: ModelPrice(
                Decimal(str(values["input_per_million"])),
                Decimal(str(values["output_per_million"])),
            )
            for name, values in raw_prices.items()
            if isinstance(name, str) and isinstance(values, dict)
        }
        if len(prices) != len(raw_prices):
            raise ValueError("each model price needs input_per_million and output_per_million")
        budget_text = os.environ.get("DAGI_BUDGET_USD")
        budget = Decimal(budget_text) if budget_text else None
        max_calls = int(os.environ.get("DAGI_MAX_PROVIDER_CALLS_PER_RUN", "32"))
        context_limit = int(os.environ.get("DAGI_CONTEXT_LIMIT_TOKENS", "32768"))
        max_tool_result_chars = int(os.environ.get("DAGI_CONTEXT_MAX_TOOL_RESULT_CHARS", "4000"))
        compression_model = os.environ.get("DAGI_COMPRESSION_MODEL", model).strip() or model
        max_delegation_depth = int(os.environ.get("DAGI_MAX_DELEGATION_DEPTH", "2"))
        max_child_agents = int(os.environ.get("DAGI_MAX_CHILD_AGENTS_PER_RUN", "3"))
        if context_limit < 1 or max_tool_result_chars < 1:
            raise ValueError("context limits must be positive")
        if max_delegation_depth < 0 or max_child_agents < 0:
            raise ValueError("delegation limits must not be negative")
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError(f"invalid usage/budget configuration: {exc}") from exc
    usage_policy = UsagePolicy(
        prices=prices,
        max_calls_per_run=max_calls,
        budget_usd=budget,
        estimate_missing=_enabled(os.environ.get("DAGI_ESTIMATE_MISSING_USAGE", "true")),
    )
    usage_policy.validate_model(model)
    usage_policy.validate_model(compression_model)
    return Config(
        api_key=api_key,
        base_url=os.environ.get("DAGI_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/"),
        model=os.environ.get("DAGI_MODEL", DEFAULT_MODEL).strip(),
        home=home,
        workspace=workspace,
        enable_shell=_enabled(os.environ.get("DAGI_ENABLE_SHELL")),
        usage_policy=usage_policy,
        compression_model=compression_model,
        context_limit_tokens=context_limit,
        context_max_tool_result_chars=max_tool_result_chars,
        max_delegation_depth=max_delegation_depth,
        max_child_agents_per_run=max_child_agents,
        web_username=os.environ.get("DAGI_WEB_USERNAME", "").strip(),
        web_password_hash=os.environ.get("DAGI_WEB_PASSWORD_HASH", "").strip(),
        web_cookie_path=os.environ.get("DAGI_WEB_COOKIE_PATH", "/").strip() or "/",
        web_public_origin=os.environ.get("DAGI_WEB_PUBLIC_ORIGIN", "").strip().rstrip("/"),
        web_cookie_secure=_enabled(os.environ.get("DAGI_WEB_COOKIE_SECURE", "true")),
    )
