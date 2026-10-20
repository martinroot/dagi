"""Run a Fabra agent on the Dagi core from the live portal.

The portal runtime v2 drives the model and the tools itself. For the agents
that passed the migration checks the Dagi core should be the one that runs:
it keeps the transcript, the tools, the workspace and the cost in one place.

This module is the bridge. It is opt in per agent package: a package whose
``runtime.backend`` is ``dagi`` is executed here instead of by runtime v2. The
bridge keeps a Dagi session per order, sends the user text, waits for the run
to finish and copies the produced files into the order workspace, so the
Fabra chat shows the same result as before.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

import engine as E
import workspace_core as W

import dagi_artifacts as DA

DEFAULT_BASE_URL = 'http://127.0.0.1:8791'
RUN_TIMEOUT = 900
STREAM_TIMEOUT = 900
POLL_SECONDS = 1.5
DELTA_CHARS = 48
DELTA_SECONDS = 0.12


def base_url() -> str:
    return (os.getenv('DAGI_ADMIN_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')


def service_token() -> str:
    return (os.getenv('DAGI_WEB_TOKEN') or '').strip()


def _headers() -> dict[str, str]:
    headers = {'Accept': 'application/json'}
    token = service_token()
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return headers


def _request(method: str, path: str, payload: dict | None = None,
             timeout: int = 120) -> tuple[int, Any]:
    url = base_url() + path
    data = None
    headers = _headers()
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', 'replace')
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as error:
        raw = error.read().decode('utf-8', 'replace')
        try:
            body = json.loads(raw)
        except Exception:
            body = {'error': raw[:400]}
        return error.code, body
    except Exception as exc:
        return 502, {'error': str(exc)}


def _stream_events(run_id: str, after: int = 0) -> Iterator[dict[str, Any]]:
    """Read the run event stream of the Dagi core.

    The core writes every event into the database, so a stream that starts
    late still receives the whole run: the events are replayed by id.
    """
    url = f'{base_url()}/api/runs/{run_id}/events?after={int(after)}'
    request = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=STREAM_TIMEOUT) as response:
            for raw in response:
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                except Exception:
                    continue
                if isinstance(event, dict):
                    yield event
    except Exception:
        return


def _template(slug: str) -> dict | None:
    status, data = _request('GET', '/api/templates')
    if status >= 400:
        return None
    return next((item for item in (data.get('templates') or []) if item.get('name') == slug), None)


def _session_id_for(number: str) -> int | None:
    state = E.get_state(E.order_dir(number))
    value = (state.get('runtime_dagi') or {}).get('session_id')
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _save_session(number: str, session_id: int) -> None:
    directory = E.order_dir(number)
    state = E.get_state(directory)
    runtime = dict(state.get('runtime_dagi') or {})
    runtime['session_id'] = session_id
    E.save_state(directory, {**state, 'runtime_dagi': runtime})


def _session_workspace(session_id: int) -> str:
    """The workspace of the session, relative to the workspace root."""
    status, snapshot = _request('GET', f'/api/sessions/{session_id}')
    if status >= 400:
        return ''
    return str((snapshot.get('session') or {}).get('workspace') or '')


def _copy_artifacts(number: str, session_id: int, workspace: str = '') -> list[str]:
    """Copy the files the Dagi run produced into the Fabra order workspace."""
    root = Path(os.getenv('DAGI_WORKSPACE_DIR') or
                '/var/www/fabra/data/dagi/workspace')
    if workspace:
        source = root / workspace
    else:
        source = root / 'sessions' / str(session_id)
    if not source.is_dir():
        return []
    target = E.order_dir(number) / 'out'
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for item in sorted(source.rglob('*')):
        if not item.is_file():
            continue
        # The same file can lie in the workspace and in the published
        # folder: the site shows one file, not two copies of one file.
        if item.name in copied:
            continue
        destination = target / item.name
        try:
            shutil.copy2(item, destination)
            copied.append(item.name)
        except OSError:
            continue
    return copied


def _publish(number: str, files: list[Path], text: str) -> tuple[list[dict], str]:
    """Register the produced files as Fabra artifacts and fix the links."""
    artifacts = DA.register(number, files)
    return artifacts, DA.rewrite_links(text, number, artifacts)


def run(number: str, instruction: str | None = None, continuation: bool = False) -> dict:
    """Execute the order on the Dagi core and return the Fabra order state."""
    directory = E.order_dir(number)
    order = E.load_json(directory / 'order.json', {})
    slug = str(order.get('slug') or '')
    if not slug:
        raise RuntimeError('order has no agent slug')

    template = _template(slug)
    if template is None:
        raise RuntimeError(f'no Dagi template for agent {slug}')

    session_id = _session_id_for(number)
    if session_id is None:
        status, clone = _request('POST', f'/api/templates/{template["id"]}/clone', {})
        if status >= 400:
            raise RuntimeError(f'clone failed: {clone.get("error")}')
        clone = clone.get('clone') or clone
        session_id = int(clone.get('session_id') or 0)
        if not session_id:
            raise RuntimeError('clone returned no session')
        _save_session(number, session_id)

    text = str(instruction or order.get('description') or order.get('title') or '').strip()
    if not text:
        text = str(template.get('task') or '')

    state = E.get_state(directory)
    E.save_state(directory, {**state, 'status': 'running', 'progress': 10})
    try:
        W.emit(number, 'runtime.started', 'Агент начал работу',
               {'runtime': 'dagi', 'session_id': session_id}, visibility='public', source='dagi')
    except Exception:
        pass

    status, started = _request('POST', f'/api/sessions/{session_id}/runs', {'message': text})
    if status >= 400:
        message = f'Dagi run failed: {started.get("error")}'
        E.save_state(directory, {**E.get_state(directory), 'status': 'failed', 'error': message})
        try:
            W.emit(number, 'job.failed', 'Агент завершился с ошибкой',
                   {'error': message}, visibility='public', source='dagi')
        except Exception:
            pass
        return E.get_state(directory)

    run_id = (started.get('run') or started).get('run_id')
    deadline = time.time() + RUN_TIMEOUT
    final = ''
    run_status = 'running'
    usage: dict = {}
    pump = _DeltaPump(number, session_id, _session_workspace(session_id))

    for event in _stream_events(run_id):
        kind = str(event.get('kind') or '')
        if kind == 'text':
            delta = str(event.get('text') or '')
            if delta:
                final += delta
                pump.add(delta)
        elif kind == 'tool_call':
            tool = str(event.get('tool_name') or '')
            if tool:
                try:
                    W.emit(number, 'runtime.tool', tool, {'tool': tool, 'runtime': 'dagi'},
                           visibility='public', source='dagi')
                except Exception:
                    pass
        elif kind == 'error':
            try:
                W.emit(number, 'job.failed', 'Агент столкнулся с ошибкой',
                       {'error': str(event.get('error') or event.get('text') or '')},
                       visibility='public', source='dagi')
            except Exception:
                pass
        elif kind == 'done':
            run_status = str(event.get('status') or 'completed')
            break
        if time.time() > deadline:
            run_status = 'timeout'
            break
    pump.flush()

    if not final or run_status == 'timeout':
        # The stream ended without the whole answer: read it from the session.
        status, snapshot = _request('GET', f'/api/sessions/{session_id}')
        if status < 400:
            answers = [item for item in (snapshot.get('messages') or [])
                       if item.get('role') == 'assistant']
            if answers:
                final = str(answers[-1].get('content') or '') or final
            runs = snapshot.get('runs') or []
            row = next((item for item in runs if item.get('run_id') == run_id),
                       runs[-1] if runs else {})
            if row:
                run_status = str(row.get('status') or run_status)

    status, detail = _request('GET', f'/api/runs/{run_id}')
    if status < 400:
        usage = detail.get('usage') or {}

    workspace = ''
    status, snapshot = _request('GET', f'/api/sessions/{session_id}')
    if status < 400:
        workspace = str((snapshot.get('session') or {}).get('workspace') or '')

    artifacts = _copy_artifacts(number, session_id, workspace)
    produced = [E.order_dir(number) / 'out' / name for name in artifacts]
    artifact_rows, final = _publish(number, produced, final)
    pump.flush()

    # The Dagi core answers in one go: when the agent needs more input it
    # asks a question instead of finishing. The Fabra chat expects that as
    # the need-info state, waiting for the user, not as a done order.
    asks = not artifacts and _looks_like_question(final)
    if asks:
        text = final.strip()
        E.agent_say(number, text)
        E.save_state(directory, {
            **E.get_state(directory),
            'status': 'needinfo',
            'progress': 40,
            'clarify_question': text,
            'final': '',
            'runtime_dagi': {
                **_session_block(number),
                'session_id': session_id,
                'run_id': run_id,
                'artifacts': artifacts,
                'artifact_ids': [row.get('artifact_id') for row in artifact_rows],
                'cost_usd': usage.get('cost_usd'),
            },
        })
        try:
            W.emit(number, 'runtime.waiting', text, {'runtime': 'dagi'},
                   visibility='public', source='dagi')
        except Exception:
            pass
    elif run_status == 'completed' and final.strip():
        E.agent_say(number, final)
        E.save_state(directory, {
            **E.get_state(directory),
            'status': 'done',
            'progress': 100,
            'final': final,
            'runtime_dagi': {
                **_session_block(number),
                'session_id': session_id,
                'run_id': run_id,
                'artifacts': artifacts,
                'artifact_ids': [row.get('artifact_id') for row in artifact_rows],
                'cost_usd': usage.get('cost_usd'),
            },
        })
        E.update_orders_status(number, 'done')
        try:
            W.emit(number, 'job.completed', 'Готово',
                   {'runtime': 'dagi', 'artifacts': artifacts},
                   visibility='public', source='dagi')
        except Exception:
            pass
    else:
        message = final.strip() or 'Dagi run did not finish'
        E.agent_say(number, message)
        E.save_state(directory, {
            **E.get_state(directory),
            'status': 'blocked' if run_status != 'failed' else 'failed',
            'error': message if run_status == 'failed' else '',
            'runtime_dagi': {
                **_session_block(number),
                'session_id': session_id,
                'run_id': run_id,
                'run_status': run_status,
            },
        })
        try:
            W.emit(number, 'job.failed', 'Агент не завершил задачу',
                   {'runtime': 'dagi', 'status': run_status},
                   visibility='public', source='dagi')
        except Exception:
            pass
    return E.get_state(directory)


class _DeltaPump:
    """Forward the text deltas of the run to the order chat.

    The chat reads the order events, so a delta is an event of its own. The
    deltas are batched: a model produces many small pieces, and the chat
    should not get one event per token.

    The sandbox link of a produced file is rewritten on the way, so the user
    never sees the path of the server. The file is published under the order
    at the end of the run, and the link of the published file replaces the
    sandbox one.
    """

    SANDBOX_LINK = re.compile(r'\(sandbox[^)]*\)')
    OPEN_LINK = re.compile(r'\(sandbox[^)]*$')

    def __init__(self, number: str, session_id: int = 0, workspace: str = ''):
        self.number = number
        self.session_id = session_id
        self.workspace = workspace
        self.buffer: list[str] = []
        self.last_flush = time.time()
        self.published: dict[str, str] = {}
        self.artifacts: list[dict[str, Any]] = []
        # The model writes a link in many small pieces, so the link is cut
        # between them. The text is kept whole until the link is closed.
        self.pending: str = ''

    def add(self, text: str) -> None:
        if not text:
            return
        self.pending += text
        self.maybe_flush()

    def maybe_flush(self, force: bool = False) -> None:
        text = self.pending
        if not text:
            return
        if not force:
            match = self.OPEN_LINK.search(text)
            if match:
                # The link is not closed yet: the text before it goes out,
                # the rest waits for the closing bracket.
                head = text[:match.start()]
                self.pending = text[match.start():]
                if head:
                    self._emit(head)
                return
            if len(text) < DELTA_CHARS and (time.time() - self.last_flush) < DELTA_SECONDS:
                return
        self.pending = ''
        self._emit(text)

    def _emit(self, text: str) -> None:
        if not text:
            return
        self.last_flush = time.time()
        try:
            W.emit(self.number, 'runtime.text', '', {'text': self._rewrite(text)},
                   visibility='public', source='dagi')
        except Exception:
            pass

    def _rewrite(self, text: str) -> str:
        """Hide the sandbox links of the produced files.

        The file is published under the order, and the finished answer of the
        transcript carries the link the site can serve. During the stream the
        link is left out, so the user never sees a path of the server.
        """
        if 'sandbox' not in text:
            return text
        return self.SANDBOX_LINK.sub('', text)

    def flush(self) -> None:
        self.maybe_flush(force=True)


def _looks_like_question(text: str) -> bool:
    """Tell a clarifying question from a finished answer."""
    stripped = str(text or '').strip()
    if not stripped:
        return False
    if stripped.rstrip().endswith(('?', '？')):
        return True
    lowered = stripped.lower()
    return any(lowered.startswith(prefix) for prefix in (
        'уточните', 'нужны', 'какой ', 'какая ', 'какие ', 'кто ', 'пришлите',
        'чтобы продолжить', 'чтобы собрать', 'не хватает', 'уточнить',
    ))


def _session_block(number: str) -> dict:
    state = E.get_state(E.order_dir(number))
    return dict(state.get('runtime_dagi') or {})
