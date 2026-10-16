import os
import stat

import pytest

from dagi_core.config import load_config


def test_config_requires_key_and_defaults_shell_off(tmp_path, monkeypatch):
    monkeypatch.delenv("DAGI_API_KEY", raising=False)
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    with pytest.raises(ValueError, match="DAGI_API_KEY"):
        load_config()

    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    config = load_config()
    assert config.enable_shell is False
    assert config.home == (tmp_path / "home").resolve()
    if os.name == "posix":
        assert stat.S_IMODE(config.home.stat().st_mode) == 0o700


def test_explicit_existing_home_directory_permissions_are_preserved(tmp_path, monkeypatch):
    home = tmp_path / "shared-home"
    home.mkdir(mode=0o755)
    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(home))

    load_config()

    if os.name == "posix":
        assert stat.S_IMODE(home.stat().st_mode) == 0o755


def test_config_accepts_openai_compatible_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_BASE_URL", "https://router.example/v1/")
    monkeypatch.setenv("DAGI_MODEL", "router/model")
    monkeypatch.setenv("DAGI_ENABLE_SHELL", "true")

    config = load_config()

    assert config.base_url == "https://router.example/v1"
    assert config.model == "router/model"
    assert config.enable_shell is True


def test_shell_confirmation_is_opt_in_and_terminal_safe(monkeypatch, capsys):
    from dagi_core.cli import approve_shell_command

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    command = "echo safe\x1b[31m"

    assert approve_shell_command(command) is False
    shown = capsys.readouterr().out
    assert r"\x1b" in shown
    assert "\x1b[31m" not in shown

    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert approve_shell_command("printf ok") is True
    monkeypatch.setattr("builtins.input", lambda _prompt: "yessir")
    assert approve_shell_command("printf no") is False


def test_cli_displays_run_id_and_terminal_status(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    import dagi_core.cli as cli

    class FinishedAgent:
        def run_turn(self, _text):
            yield SimpleNamespace(
                kind="done", session_id=1, run_id="run-123", tool_call_id=None,
                tool_name=None, tool_args=None, text=None, status="completed",
            )

    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_WORKSPACE", str(tmp_path / "workspace"))
    inputs = iter(["hello", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
    monkeypatch.setattr(cli, "_new_agent", lambda *_args: FinishedAgent())

    cli.run()

    assert "[run-123] completed" in capsys.readouterr().out


def test_config_parses_usage_prices_and_budgets(tmp_path, monkeypatch):
    from decimal import Decimal

    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_MODEL", "test-model")
    monkeypatch.setenv("DAGI_MODEL_PRICES", '{"test-model":{"input_per_million":"0.15","output_per_million":"0.60"}}')
    monkeypatch.setenv("DAGI_MAX_PROVIDER_CALLS_PER_RUN", "7")
    monkeypatch.setenv("DAGI_BUDGET_USD", "0.25")
    monkeypatch.setenv("DAGI_ESTIMATE_MISSING_USAGE", "false")

    config = load_config()

    assert config.usage_policy.max_calls_per_run == 7
    assert config.usage_policy.budget_usd == Decimal("0.25")
    assert config.usage_policy.prices["test-model"].input_per_million == Decimal("0.15")
    assert config.usage_policy.estimate_missing is False


def test_config_requires_price_for_configured_money_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_MODEL", "unpriced-model")
    monkeypatch.setenv("DAGI_BUDGET_USD", "1.00")
    monkeypatch.delenv("DAGI_MODEL_PRICES", raising=False)

    with pytest.raises(ValueError, match="price"):
        load_config()


def test_cli_can_resume_an_existing_session(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    import dagi_core.cli as cli
    from dagi_core.state import StateStore

    home = tmp_path / "home"
    seed = StateStore(home / "state.sqlite3")
    saved_session = seed.create_session("saved")
    seed.close()

    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(home))
    monkeypatch.setenv("DAGI_WORKSPACE", str(tmp_path / "workspace"))
    inputs = iter([f"/resume {saved_session}", "hello", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
    selected = []

    class FinishedAgent:
        def __init__(self, session_id):
            self.session_id = session_id

        def run_turn(self, _text):
            yield SimpleNamespace(
                kind="done", session_id=self.session_id, run_id="resumed-run",
                tool_call_id=None, tool_name=None, tool_args=None, text=None, status="completed",
            )

    def build_agent(_config, _provider, state, session_id=None):
        selected_id = session_id if session_id is not None else state.create_session()
        selected.append(selected_id)
        return FinishedAgent(selected_id)

    monkeypatch.setattr(cli, "_new_agent", build_agent)
    cli.run()

    assert selected[-1] == saved_session
    assert f"Resumed session {saved_session}" in capsys.readouterr().out
