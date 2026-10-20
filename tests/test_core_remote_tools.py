"""The remote tools of the core.

The Fabra agents that set up a server need to look at it and to change it.
A command that changes something has to be approved by the user first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dagi_core import remote
from dagi_core.state import StateStore
from dagi_core.tools import ToolError, ToolRegistry


def make_tools(tmp_path: Path, approve=None):
    state = StateStore(tmp_path / 'state.sqlite3')
    session = state.create_session()
    workspace = tmp_path / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    return state, ToolRegistry(workspace, state, session, approve_shell=approve)


def test_the_inspect_reports_the_server(tmp_path, monkeypatch):
    calls: list = []

    def run(args, timeout=120):
        calls.append(args)
        return 0, 'the output of the command', ''

    monkeypatch.setattr(remote, '_run', run)
    state, tools = make_tools(tmp_path)

    result = tools.call('ssh_inspect', {'host': 'server.example', 'user': 'root'})

    assert 'the output of the command' in result.content
    assert calls
    assert 'root@server.example' in calls[0]


def test_the_inspect_uses_the_port_and_the_key(tmp_path, monkeypatch):
    calls: list = []

    def run(args, timeout=120):
        calls.append(args)
        return 0, 'ok', ''

    monkeypatch.setattr(remote, '_run', run)
    key = tmp_path / 'id_ed25519'
    key.write_text('key', encoding='utf-8')
    state, tools = make_tools(tmp_path)

    tools.call('ssh_inspect', {'host': 'server.example', 'user': 'root',
                               'port': '2222', 'key': str(key)})

    assert '-p' in calls[0] and '2222' in calls[0]
    assert '-i' in calls[0]


def test_the_inspect_refuses_a_wrong_host(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, '_run', lambda args, timeout=120: (0, '', ''))
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('ssh_inspect', {'host': 'bad host; rm -rf /', 'user': 'root'})


def test_the_inspect_refuses_a_missing_user(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, '_run', lambda args, timeout=120: (0, '', ''))
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('ssh_inspect', {'host': 'server.example', 'user': ''})


def test_the_command_runs_on_the_server(tmp_path, monkeypatch):
    calls: list = []

    def run(args, timeout=120):
        calls.append(args)
        return 0, 'done', ''

    monkeypatch.setattr(remote, '_run', run)
    state, tools = make_tools(tmp_path)

    result = tools.call('ssh_exec_write', {
        'host': 'server.example', 'user': 'root', 'command': 'systemctl restart nginx',
    })

    assert 'exit code 0' in result.content
    assert calls[-1][-1] == 'systemctl restart nginx'


def test_the_command_needs_the_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, '_run', lambda args, timeout=120: (0, '', ''))
    state, tools = make_tools(tmp_path, approve=lambda reason: False)

    with pytest.raises(ToolError):
        tools.call('ssh_exec_write', {
            'host': 'server.example', 'user': 'root', 'command': 'rm -rf /var',
        })


def test_the_approved_command_runs(tmp_path, monkeypatch):
    seen: list = []

    def run(args, timeout=120):
        seen.append(args)
        return 0, 'ok', ''

    monkeypatch.setattr(remote, '_run', run)
    state, tools = make_tools(tmp_path, approve=lambda reason: seen.append(reason) or True)

    tools.call('ssh_exec_write', {
        'host': 'server.example', 'user': 'root', 'command': 'apt update',
    })

    assert seen and isinstance(seen[0], str)


def test_the_command_needs_a_command(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, '_run', lambda args, timeout=120: (0, '', ''))
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('ssh_exec_write', {'host': 'server.example', 'user': 'root', 'command': ' '})
