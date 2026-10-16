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
