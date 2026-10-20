"""The video tool of the core.

The Fabra agent that turns a photo into a short video needs a video
provider, and the core had no counterpart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dagi_core import media_video
from dagi_core.state import StateStore
from dagi_core.tools import ToolError, ToolRegistry


def make_tools(tmp_path: Path):
    state = StateStore(tmp_path / 'state.sqlite3')
    session = state.create_session()
    workspace = tmp_path / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    return state, ToolRegistry(workspace, state, session)


def fake_provider(monkeypatch, calls: list):
    """Answer the provider with a finished video."""
    def queue(model: str, payload: dict):
        calls.append((model, payload))
        return 'https://provider.test/status', 'https://provider.test/response'

    def await_result(status_url: str, response_url: str, timeout: int):
        return {'video': {'url': 'https://provider.test/video.mp4'}}

    def download(url: str, timeout: int = 120):
        return b'video-bytes'

    monkeypatch.setattr(media_video, '_queue', queue)
    monkeypatch.setattr(media_video, '_await', await_result)
    monkeypatch.setattr(media_video, '_download', download)


def test_the_video_is_written_into_the_workspace(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'photo.png').write_bytes(b'photo')

    result = tools.call('video_generate', {'input': 'photo.png', 'prompt': 'it rolls away'})

    assert (tools.workspace / 'video.mp4').is_file()
    assert result.content == 'video.mp4'
    assert calls and calls[0][1]['prompt'] == 'it rolls away'
    assert calls[0][1]['image_url'].startswith('data:image/png;base64,')


def test_the_video_needs_a_picture(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('video_generate', {'input': 'nothing.png', 'prompt': 'it rolls away'})


def test_the_video_needs_a_prompt(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'photo.png').write_bytes(b'photo')

    with pytest.raises(ToolError):
        tools.call('video_generate', {'input': 'photo.png', 'prompt': '  '})


def test_the_video_reports_the_file_as_an_artifact(tmp_path, monkeypatch):
    calls: list = []
    fake_provider(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'photo.png').write_bytes(b'photo')

    result = tools.call('video_generate', {'input': 'photo.png', 'prompt': 'it rolls away'})

    artifacts = (result.presentation or {}).get('artifacts') or []
    assert artifacts
    assert artifacts[0]['kind'] == 'video'
