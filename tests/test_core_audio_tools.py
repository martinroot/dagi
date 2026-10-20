"""The audio, music and video tools of the core.

The Fabra agents speak, listen, sing and cut video, and the core had no
counterpart for any of it.

The tests use fake providers: the tools must write the file into the
workspace and report it as an artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dagi_core import media_audio
from dagi_core.state import StateStore
from dagi_core.tools import ToolError, ToolRegistry


def make_tools(tmp_path: Path):
    state = StateStore(tmp_path / 'state.sqlite3')
    session = state.create_session()
    workspace = tmp_path / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    return state, ToolRegistry(workspace, state, session)


def fake_queue(monkeypatch, calls: list, audio_url: str = 'https://provider.test/a.mp3'):
    """Answer every queued request with a finished one."""
    def request(url: str, method: str = 'GET', payload: dict | None = None, timeout: int = 60):
        calls.append((url, method, payload))
        if url.endswith('/status'):
            return {'status': 'COMPLETED', 'audio': {'url': audio_url},
                    'text': 'the spoken words'}
        if method == 'POST':
            return {'request_id': 'req-1', 'status_url': url + '/status',
                    'response_url': url}
        return {'audio': {'url': audio_url}, 'text': 'the spoken words'}

    monkeypatch.setattr(media_audio, '_request', request)
    monkeypatch.setattr(media_audio, '_download', lambda url, timeout=120: b'audio-bytes')
    monkeypatch.setenv('DAGI_FAL_KEY', 'test-key')


def test_music_writes_the_song(tmp_path, monkeypatch):
    calls: list = []
    fake_queue(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    result = tools.call('music_generate', {'lyrics': '[verse] hello', 'prompt': 'lofi beat'})

    assert (tools.workspace / 'music.mp3').is_file()
    assert result.content == 'music.mp3'
    posted = [call for call in calls if call[1] == 'POST'][0]
    assert posted[2]['lyrics'] == '[Verse] hello'


def test_music_needs_both_parts(tmp_path, monkeypatch):
    calls: list = []
    fake_queue(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('music_generate', {'lyrics': 'hello', 'prompt': ''})


def test_music_refuses_the_same_text_twice(tmp_path, monkeypatch):
    calls: list = []
    fake_queue(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('music_generate', {'lyrics': 'hello', 'prompt': 'hello'})


def test_transcribe_writes_the_words(tmp_path, monkeypatch):
    calls: list = []
    fake_queue(monkeypatch, calls)
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'talk.mp3').write_bytes(b'audio')
    monkeypatch.setattr(media_audio, '_queue_audio', lambda model, path: ('https://provider.test/status', 'https://provider.test/response'))

    result = tools.call('audio_transcribe', {'input': 'talk.mp3'})

    assert (tools.workspace / 'transcript.txt').read_text() == 'the spoken words'
    assert 'the spoken words' in result.content


def test_transcribe_refuses_a_missing_file(tmp_path, monkeypatch):
    calls: list = []
    fake_queue(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('audio_transcribe', {'input': 'nothing.mp3'})


def test_speak_writes_the_audio(tmp_path, monkeypatch):
    calls: list = []
    fake_queue(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    result = tools.call('audio_synthesize', {'text': 'привет'})

    assert (tools.workspace / 'speech.mp3').is_file()
    assert result.content == 'speech.mp3'


def test_speak_needs_a_text(tmp_path, monkeypatch):
    calls: list = []
    fake_queue(monkeypatch, calls)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('audio_synthesize', {'text': '  '})


def test_the_read_only_command_runs(tmp_path):
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'note.txt').write_text('hello', encoding='utf-8')

    result = tools.call('shell_readonly', {'command': 'cat note.txt'})

    assert 'hello' in result.content


def test_the_read_only_command_refuses_anything_else(tmp_path):
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('shell_readonly', {'command': 'rm -rf /'})


def test_the_fal_key_is_required(tmp_path, monkeypatch):
    monkeypatch.delenv('DAGI_FAL_KEY', raising=False)
    monkeypatch.delenv('FAL_KEY', raising=False)

    with pytest.raises(media_audio.MediaError):
        media_audio.music(tmp_path, 'hello', 'lofi')
