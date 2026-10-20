"""The voice of the core without the queue of fal.

The queue of fal runs out of money from time to time, and the cards of the
site still have to speak and listen. The provider of the core gives a voice
and reads a file as well, so it is the second road of the core.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from dagi_core import voice
from dagi_core.state import StateStore
from dagi_core.tools import ToolError, ToolRegistry


def make_tools(tmp_path: Path):
    state = StateStore(tmp_path / 'state.sqlite3')
    session = state.create_session()
    workspace = tmp_path / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    return state, ToolRegistry(workspace, state, session)


def fake_stream(monkeypatch, pcm: bytes = b'\x00\x01' * 100):
    def post_stream(body: dict, timeout: int = 240):
        event = {
            'choices': [{'delta': {'audio': {'data': base64.b64encode(pcm).decode('ascii')}}}],
        }
        return 'data: ' + json.dumps(event) + '\n\ndata: [DONE]\n'

    monkeypatch.setattr(voice, '_post_stream', post_stream)
    monkeypatch.setenv('DAGI_API_KEY', 'test-key')


def test_the_voice_is_written_as_a_wav(tmp_path, monkeypatch):
    fake_stream(monkeypatch)
    state, tools = make_tools(tmp_path)

    result = tools.call('audio_synthesize', {'text': 'Проверка голоса', 'filename': 'voice.mp3'})

    target = tools.workspace / 'voice.wav'
    assert target.is_file()
    assert target.read_bytes()[:4] == b'RIFF'
    assert result.content == 'voice.wav'


def test_the_voice_needs_a_text(tmp_path, monkeypatch):
    fake_stream(monkeypatch)
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('audio_synthesize', {'text': '  '})


def test_the_voice_uses_the_model_of_the_provider(tmp_path, monkeypatch):
    seen: list = []

    def post_stream(body: dict, timeout: int = 240):
        seen.append(body)
        event = {'choices': [{'delta': {'audio': {'data': base64.b64encode(b'\x00').decode()}}}]}
        return 'data: ' + json.dumps(event) + '\n'

    monkeypatch.setattr(voice, '_post_stream', post_stream)
    monkeypatch.setenv('DAGI_API_KEY', 'test-key')
    state, tools = make_tools(tmp_path)

    tools.call('audio_synthesize', {'text': 'Проверка голоса'})

    assert seen
    assert seen[0]['model'] == voice.speech_model()
    assert seen[0]['modalities'] == ['text', 'audio']


def test_the_words_of_a_file_are_written(tmp_path, monkeypatch):
    def post(body: dict, timeout: int = 240):
        return {
            'choices': [{'message': {'content': 'Привет, это проверка.'}}],
            'usage': {'cost': 0.00007},
        }

    monkeypatch.setattr(voice, '_post', post)
    monkeypatch.setenv('DAGI_API_KEY', 'test-key')
    state, tools = make_tools(tmp_path)
    (tools.workspace / 'voice.wav').write_bytes(b'RIFF....')

    result = tools.call('audio_transcribe', {'input': 'voice.wav', 'filename': 'words.txt'})

    target = tools.workspace / 'words.txt'
    assert target.is_file()
    assert 'проверка' in target.read_text(encoding='utf-8')
    # The agent reads the words of the file, not the name of it.
    assert result.content == 'Привет, это проверка.'
    artifacts = (result.presentation or {}).get('artifacts') or []
    assert artifacts
    assert artifacts[0]['path'] == 'words.txt'


def test_the_words_need_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, '_post', lambda body, timeout=240: {})
    monkeypatch.setenv('DAGI_API_KEY', 'test-key')
    state, tools = make_tools(tmp_path)

    with pytest.raises(ToolError):
        tools.call('audio_transcribe', {'input': 'nothing.wav'})
