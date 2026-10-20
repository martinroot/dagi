"""The picture merge tool of the core.

The Fabra agent that combines two pictures has no counterpart in the core.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from dagi_core import media_merge
from dagi_core.state import StateStore
from dagi_core.tools import ToolError, ToolRegistry

PNG = base64.b64encode(b'fake-png-bytes').decode('ascii')


def make_tools(tmp_path: Path):
    state = StateStore(tmp_path / 'state.sqlite3')
    session = state.create_session()
    workspace = tmp_path / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    return state, ToolRegistry(workspace, state, session)


def fake_provider(monkeypatch, calls: list):
    def post(body: dict, timeout: int = 240):
        calls.append(body)
        return {
            'model': body.get('model'),
            'choices': [{'message': {'images': [
                {'image_url': {'url': f'data:image/png;base64,{PNG}'}}
            ]}}],
            'usage': {'cost': 0.06},
        }

    monkeypatch.setattr(media_merge, '_post', post)
    monkeypatch.setenv('DAGI_API_KEY', 'test-key')


def test_the_merge_sends_both_pictures(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'a.png').write_bytes(b'a')
    (tools.workspace / 'b.png').write_bytes(b'b')

    result = tools.call('image_merge_prompt', {
        'first': 'a.png', 'second': 'b.png', 'prompt': 'put the cat on the bike',
    })

    assert (tools.workspace / 'merged.png').is_file()
    assert result.content == 'merged.png'
    parts = calls[0]['messages'][0]['content']
    images = [part for part in parts if part.get('type') == 'image_url']
    assert len(images) == 2
    assert base64.b64decode(images[0]['image_url']['url'].split(',', 1)[1]) == b'a'
    assert base64.b64decode(images[1]['image_url']['url'].split(',', 1)[1]) == b'b'


def test_the_merge_needs_a_prompt(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'a.png').write_bytes(b'a')
    (tools.workspace / 'b.png').write_bytes(b'b')

    with pytest.raises(ToolError):
        tools.call('image_merge_prompt', {'first': 'a.png', 'second': 'b.png', 'prompt': ' '})


def test_the_merge_refuses_a_missing_picture(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'a.png').write_bytes(b'a')

    with pytest.raises(ToolError):
        tools.call('image_merge_prompt', {'first': 'a.png', 'second': 'b.png', 'prompt': 'mix'})


def test_the_merge_reports_the_picture_as_an_artifact(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'a.png').write_bytes(b'a')
    (tools.workspace / 'b.png').write_bytes(b'b')

    result = tools.call('image_merge_prompt', {
        'first': 'a.png', 'second': 'b.png', 'prompt': 'mix',
    })

    artifacts = (result.presentation or {}).get('artifacts') or []
    assert artifacts
    assert artifacts[0]['kind'] == 'image'
