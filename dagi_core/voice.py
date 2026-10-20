"""The voice and the words of a file, without the queue of fal.

The queue of fal runs out of money from time to time, and the cards of the
site still have to speak and listen. The provider of the core gives a voice
and reads a file as well, and it costs almost nothing, so it is the second
road of the core: the queue first, the provider of the core when the queue
is closed.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
SPEECH_MODEL = 'openai/gpt-audio-mini'
TRANSCRIBE_MODEL = 'openai/gpt-audio-mini'
SAMPLE_RATE = 24000
VOICES = ('alloy', 'nova', 'echo', 'sage', 'shimmer', 'onyx', 'fable')


class VoiceError(Exception):
    """A provider call that did not work."""


def api_key() -> str:
    return (os.getenv('DAGI_API_KEY') or os.getenv('OPENROUTER_API_KEY') or '').strip()


def base_url() -> str:
    return (os.getenv('DAGI_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')


def speech_model() -> str:
    return (os.getenv('DAGI_SPEECH_MODEL') or SPEECH_MODEL).strip()


def transcribe_model() -> str:
    return (os.getenv('DAGI_TRANSCRIBE_MODEL') or TRANSCRIBE_MODEL).strip()


def _headers() -> dict[str, str]:
    key = api_key()
    if not key:
        raise VoiceError('the provider key is not configured')
    return {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': os.getenv('OPENROUTER_SITE_URL') or 'https://fabra.live',
        'X-Title': os.getenv('OPENROUTER_APP_NAME') or 'Fabra',
    }


def _post_stream(body: dict[str, Any], timeout: int = 240) -> str:
    request = urllib.request.Request(
        f'{base_url()}/chat/completions',
        data=json.dumps(body).encode('utf-8'),
        headers=_headers(),
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', 'replace')[:300]
        raise VoiceError(f'provider error {error.code}: {detail}') from error
    except Exception as exc:
        raise VoiceError(f'provider call failed: {exc}') from exc


def _post(body: dict[str, Any], timeout: int = 240) -> dict[str, Any]:
    request = urllib.request.Request(
        f'{base_url()}/chat/completions',
        data=json.dumps(body).encode('utf-8'),
        headers=_headers(),
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', 'replace')
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', 'replace')[:300]
        raise VoiceError(f'provider error {error.code}: {detail}') from error
    except Exception as exc:
        raise VoiceError(f'provider call failed: {exc}') from exc


def wav_from_pcm(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw pcm into a wav file, so any player can hear it."""
    header = b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVE'
    header += b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16)
    header += b'data' + struct.pack('<I', len(pcm))
    return header + pcm


def speak(workspace: Path, text: str, filename: str = 'speech.wav',
          voice: str = 'alloy') -> dict[str, Any]:
    """Read a text out loud."""
    words = str(text or '').strip()
    if not words:
        raise VoiceError('a text is required')
    name = str(voice or 'alloy')
    if name not in VOICES:
        name = 'alloy'
    body = {
        'model': speech_model(),
        'messages': [{'role': 'user', 'content': words}],
        'modalities': ['text', 'audio'],
        'audio': {'voice': name, 'format': 'pcm16'},
        'stream': True,
    }
    raw = _post_stream(body)
    pieces: list[str] = []
    for line in raw.splitlines():
        if not line.startswith('data:'):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == '[DONE]':
            continue
        try:
            event = json.loads(chunk)
        except Exception:
            continue
        delta = (event.get('choices') or [{}])[0].get('delta') or {}
        audio = delta.get('audio') or {}
        if audio.get('data'):
            pieces.append(str(audio['data']))
    if not pieces:
        raise VoiceError('the provider returned no voice')
    pcm = base64.b64decode(''.join(pieces))
    content = wav_from_pcm(pcm)
    target_name = Path(filename or 'speech.wav').name
    if target_name.endswith('.mp3'):
        target_name = target_name[:-4] + '.wav'
    target = workspace / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {
        'path': target_name,
        'size_bytes': len(content),
        'mime': 'audio/wav',
        'model': speech_model(),
    }


def transcribe(workspace: Path, path: str, filename: str = 'transcript.txt') -> dict[str, Any]:
    """Write the words of an audio file."""
    source = Path(path)
    if not source.is_file():
        raise VoiceError(f'not a file: {path!r}')
    fmt = (mimetypes.guess_type(source.name)[0] or 'audio/mpeg').split('/')[-1]
    if fmt == 'mpeg':
        fmt = 'mp3'
    encoded = base64.b64encode(source.read_bytes()).decode('ascii')
    body = {
        'model': transcribe_model(),
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Transcribe this audio. Answer with the words only.'},
            {'type': 'input_audio', 'input_audio': {'data': encoded, 'format': fmt}},
        ]}],
    }
    data = _post(body)
    message = (data.get('choices') or [{}])[0].get('message') or {}
    text = str(message.get('content') or '').strip()
    if not text:
        raise VoiceError('the provider returned no words')
    name = Path(filename or 'transcript.txt').name
    target = workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    usage = data.get('usage') or {}
    return {
        'path': name,
        'size_bytes': len(text.encode('utf-8')),
        'mime': 'text/plain',
        'text': text,
        'cost_usd': float(usage.get('cost') or 0),
        'model': transcribe_model(),
    }
