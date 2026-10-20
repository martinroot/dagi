"""The image tools of the core.

The Fabra agents draw and edit pictures, and the core had no counterpart, so
the agents that need a picture had a tool gap and could not be shipped to
the site.

The tests use a fake provider: the tools must write the file into the
workspace, report it as an artifact and keep the cost of the call.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from dagi_core import media
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
    """Answer every provider call with one image."""
    def post(body: dict, timeout: int = 240):
        calls.append(body)
        return {
            'model': body.get('model'),
            'choices': [{'message': {'images': [
                {'image_url': {'url': f'data:image/png;base64,{PNG}'}}
            ]}}],
            'usage': {'cost': 0.05},
        }

    monkeypatch.setattr(media, '_post', post)
    monkeypatch.setenv('DAGI_API_KEY', 'test-key')


def test_generate_writes_the_image_into_the_workspace(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    result = tools.call('image_generate', {'prompt': 'a red bicycle'})

    assert (tools.workspace / 'generated.png').is_file()
    assert result.content == 'generated.png'
    assert calls and calls[0]['modalities'] == ['image', 'text']
    assert calls[0]['messages'][0]['content'][0]['text'] == 'a red bicycle'


def test_generate_reports_the_image_as_an_artifact(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    result = tools.call('image_generate', {'prompt': 'a red bicycle'})

    artifacts = (result.presentation or {}).get('artifacts') or []
    assert artifacts
    assert artifacts[0]['kind'] == 'image'


def test_generate_needs_a_prompt(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('image_generate', {'prompt': '  '})


def test_edit_sends_the_source_image(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'photo.jpg').write_bytes(b'source-bytes')

    tools.call('image_edit', {'input': 'photo.jpg', 'prompt': 'make it winter'})

    parts = calls[0]['messages'][0]['content']
    image_part = [part for part in parts if part.get('type') == 'image_url'][0]
    sent = image_part['image_url']['url']
    assert sent.startswith('data:image/')
    assert base64.b64decode(sent.split(',', 1)[1]) == b'source-bytes'


def test_edit_refuses_a_missing_source(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('image_edit', {'input': 'nothing.jpg', 'prompt': 'make it winter'})


def test_batch_packs_the_results_into_an_archive(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'a.jpg').write_bytes(b'a')
    (tools.workspace / 'b.jpg').write_bytes(b'b')

    result = tools.call('image_edit_batch', {
        'inputs': ['a.jpg', 'b.jpg'],
        'prompt': 'add snow',
    })

    assert (tools.workspace / 'result-results.zip').is_file()
    assert result.content == 'result-results.zip'
    assert len(calls) == 2


def test_batch_needs_at_least_one_input(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('image_edit_batch', {'inputs': [], 'prompt': 'add snow'})


def test_the_provider_key_is_required(tmp_path, monkeypatch):
    monkeypatch.delenv('DAGI_API_KEY', raising=False)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)

    with pytest.raises(media.MediaError):
        media.generate(tmp_path, 'a red bicycle')


def test_an_answer_without_an_image_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(media, '_post', lambda body, timeout=240: {'choices': [{'message': {}}]})
    monkeypatch.setenv('DAGI_API_KEY', 'test-key')

    with pytest.raises(media.MediaError):
        media.generate(tmp_path, 'a red bicycle')
