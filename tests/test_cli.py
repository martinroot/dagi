from hermes.cli import DagiCLI


def test_shell_command_requires_interactive_yes(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    approved = DagiCLI._approve_shell("touch never-run")

    assert approved is False
    assert "touch never-run" in capsys.readouterr().out


def test_shell_command_is_approved_only_for_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")

    assert DagiCLI._approve_shell("echo approved") is True


def test_shell_prompt_escapes_terminal_control_characters(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    DagiCLI._approve_shell("echo safe\x1b[31m")

    output = capsys.readouterr().out
    assert "\\x1b" in output
    assert "\x1b[31m" not in output
