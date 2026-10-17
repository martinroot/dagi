import json
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


def test_command_checks_are_disabled_unless_operator_sets_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DAGI_ENABLE_CHECK_COMMANDS", raising=False)
    assert load_config().enable_check_commands is False

    monkeypatch.setenv("DAGI_ENABLE_CHECK_COMMANDS", "true")
    assert load_config().enable_check_commands is True


def test_config_repr_omits_credentials_and_session_verifier(tmp_path, monkeypatch):
    api_key = "api-key-test-not-real"
    password_hash = "pbkdf2-test-verifier-not-real"
    web_token = "web-token-test-not-real"
    monkeypatch.setenv("DAGI_API_KEY", api_key)
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_WEB_PASSWORD_HASH", password_hash)
    monkeypatch.setenv("DAGI_WEB_TOKEN", web_token)

    displayed = repr(load_config())

    assert api_key not in displayed
    assert password_hash not in displayed
    assert web_token not in displayed


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
        def run_turn(self, _text, session_id=None):
            yield SimpleNamespace(
                kind="done", session_id=session_id, run_id="run-123", tool_call_id=None,
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


def test_config_loads_context_limit_and_compression_model(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_MODEL", "main-model")
    monkeypatch.setenv("DAGI_CONTEXT_LIMIT_TOKENS", "4096")
    monkeypatch.setenv("DAGI_CONTEXT_MAX_TOOL_RESULT_CHARS", "1200")
    monkeypatch.setenv("DAGI_COMPRESSION_MODEL", "small-compressor")

    config = load_config()

    assert config.context_limit_tokens == 4096
    assert config.context_max_tool_result_chars == 1200
    assert config.compression_model == "small-compressor"


def test_config_parses_delegation_depth_and_child_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_MAX_DELEGATION_DEPTH", "2")
    monkeypatch.setenv("DAGI_MAX_CHILD_AGENTS_PER_RUN", "3")

    config = load_config()

    assert config.max_delegation_depth == 2
    assert config.max_child_agents_per_run == 3


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
    inputs = iter([f"/resume {saved_session}", "hello", "/new", "new-session turn", f"/resume {saved_session}", "again", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
    selected = []
    agent_builds = []

    class FinishedAgent:
        def run_turn(self, text, session_id=None):
            selected.append((text, session_id))
            yield SimpleNamespace(
                kind="done", session_id=session_id, run_id="resumed-run",
                tool_call_id=None, tool_name=None, tool_args=None, text=None, status="completed",
            )

    def build_agent(_config, _provider, _state, session_id=None):
        agent_builds.append(session_id)
        return FinishedAgent()

    monkeypatch.setattr(cli, "_new_agent", build_agent)
    cli.run()

    assert len(agent_builds) == 1
    assert [item[1] for item in selected][0] == saved_session
    assert [item[1] for item in selected][2] == saved_session
    assert [item[1] for item in selected][1] != saved_session
    assert f"Resumed session {saved_session}" in capsys.readouterr().out


def test_cli_resume_uses_saved_session_workspace(tmp_path, monkeypatch, capsys):
    import dagi_core.cli as cli
    from dagi_core.provider import StreamEvent
    from dagi_core.state import StateStore

    home = tmp_path / "home"
    seed = StateStore(home / "state.sqlite3")
    saved_session = seed.create_session("saved")
    seed.set_session_workspace(saved_session, ".dagi-children/cli-child")
    seed.close()

    monkeypatch.setenv("DAGI_API_KEY", "placeholder-for-test")
    monkeypatch.setenv("DAGI_HOME", str(home))
    monkeypatch.setenv("DAGI_WORKSPACE", str(tmp_path / "workspace"))
    inputs = iter([f"/resume {saved_session}", "create a file", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    class ToolProvider:
        model = "main-model"

        def __init__(self):
            self.calls = 0
            self.requests = []

        def stream(self, messages, _tools):
            self.requests.append(messages)
            self.calls += 1
            if self.calls == 1:
                return iter([
                    StreamEvent(kind="tool_call", tool_call={
                        "id": "cli-workspace-call", "name": "write_file",
                        "arguments": {"path": "from-cli.txt", "content": "session scoped"},
                    }),
                    StreamEvent(kind="usage", usage={"input_tokens": 10, "output_tokens": 2}),
                    StreamEvent(kind="finish", finish_reason="tool_calls"),
                ])
            return iter([
                StreamEvent(kind="text", text="Saved in this session."),
                StreamEvent(kind="usage", usage={"input_tokens": 8, "output_tokens": 3}),
                StreamEvent(kind="finish", finish_reason="stop"),
            ])

    provider = ToolProvider()
    monkeypatch.setattr(cli, "OpenAICompatibleProvider", lambda *_args: provider)

    cli.run()

    child_workspace = tmp_path / "workspace" / ".dagi-children" / "cli-child"
    system_content = provider.requests[0][0]["content"]
    start = system_content.index("DAGI_RUNTIME_CONTEXT_JSON_BEGIN\n") + len("DAGI_RUNTIME_CONTEXT_JSON_BEGIN\n")
    end = system_content.index("\nDAGI_RUNTIME_CONTEXT_JSON_END", start)
    runtime_context = json.loads(system_content[start:end])
    assert runtime_context["environment"]["entry_point"] == "cli"
    assert runtime_context["environment"]["workspace"] == ".dagi-children/cli-child"
    assert (child_workspace / "from-cli.txt").read_text(encoding="utf-8") == "session scoped"
    assert not (tmp_path / "workspace" / "from-cli.txt").exists()
    assert "Saved in this session." in capsys.readouterr().out
