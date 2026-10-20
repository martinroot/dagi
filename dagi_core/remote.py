"""Remote access tools for the Dagi core.

The Fabra agents that set up a server need to look at it and to change it.
The core had no counterpart, so those agents could not run on it.

The tools speak ssh with the binary of the system. The connection comes from
the order: the host, the user, the port and the key of the user. A key is
preferred over a password, and every command that changes something has to
be approved by the user first.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

SSH_TIMEOUT = 120
INSPECT_COMMANDS = (
    'uname -a', 'cat /etc/os-release', 'df -h', 'free -m', 'ls -la /',
    'systemctl list-units --type=service --state=running',
    'nginx -v', 'php -v', 'node --version', 'python3 --version',
    'docker ps', 'ss -tlnp',
)
HOST_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,255}$')
USER_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


class RemoteError(Exception):
    """A remote call that did not work."""


def ssh_binary() -> str:
    path = shutil.which('ssh')
    if not path:
        raise RemoteError('ssh is not installed')
    return path


def _check_host(host: str) -> str:
    name = str(host or '').strip()
    if not name or not HOST_PATTERN.match(name):
        raise RemoteError('the host is missing or looks wrong')
    return name


def _check_user(user: str) -> str:
    name = str(user or '').strip()
    if not name or not USER_PATTERN.match(name):
        raise RemoteError('the user is missing or looks wrong')
    return name


def _check_port(port: Any) -> int:
    try:
        value = int(port or 22)
    except (TypeError, ValueError):
        raise RemoteError('the port is not a number') from None
    if not 1 <= value <= 65535:
        raise RemoteError('the port is out of range')
    return value


def connection_args(host: str, user: str, port: Any = 22, key: str = '') -> list[str]:
    """The arguments of the ssh call for a connection."""
    name = _check_host(host)
    who = _check_user(user)
    number = _check_port(port)
    args = [ssh_binary(), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
            '-o', f'ConnectTimeout=15', '-p', str(number)]
    key_path = str(key or '').strip()
    if key_path:
        path = Path(key_path)
        if not path.is_file():
            raise RemoteError(f'the key is not there: {path.name}')
        args += ['-i', str(path)]
    args += [f'{who}@{name}']
    return args


def _run(args: list[str], timeout: int = SSH_TIMEOUT) -> tuple[int, str, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RemoteError('the remote call took too long') from exc
    except Exception as exc:
        raise RemoteError(f'the remote call failed: {exc}') from exc
    return result.returncode, result.stdout[-20000:], result.stderr[-4000:]


def inspect(host: str, user: str, port: Any = 22, key: str = '',
            commands: list[str] | None = None) -> dict[str, Any]:
    """Look at a remote server without changing anything."""
    base = connection_args(host, user, port, key)
    wanted = list(commands or INSPECT_COMMANDS)
    report: list[dict[str, Any]] = []
    for command in wanted:
        code, out, err = _run(base + [command], timeout=60)
        report.append({
            'command': command,
            'code': code,
            'stdout': out.strip()[:4000],
            'stderr': err.strip()[:1000],
        })
    return {'host': host, 'user': user, 'report': report}


def execute(host: str, user: str, command: str, port: Any = 22, key: str = '',
            timeout: int = SSH_TIMEOUT) -> dict[str, Any]:
    """Run a command on a remote server. The caller has to approve it first."""
    text = str(command or '').strip()
    if not text:
        raise RemoteError('a command is required')
    base = connection_args(host, user, port, key)
    code, out, err = _run(base + [text], timeout=timeout)
    return {
        'host': host,
        'user': user,
        'command': text,
        'code': code,
        'stdout': out[-20000:],
        'stderr': err[-4000:],
    }
