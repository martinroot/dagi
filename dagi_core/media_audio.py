"""Audio, music and video tools for the Dagi core.

The Fabra agents speak, listen, sing and cut video, and the core had no
counterpart for any of it. The providers are the ones the site already
uses: the queue of fal for the speech and the music, and the local ffmpeg
for the video work.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

FAL_QUEUE = 'https://queue.fal.run'
MUSIC_MODEL = 'fal-ai/minimax-music/v2.6'
SPEECH_MODEL = 'fal-ai/minimax/speech-02-hd'
TRANSCRIBE_MODEL = 'fal-ai/whisper'
MUSIC_TIMEOUT = 420
FFMPEG_TIMEOUT = 300


class MediaError(Exception):
    """A provider call that did not work."""


def fal_key() -> str:
    return (os.getenv('DAGI_FAL_KEY') or os.getenv('FAL_KEY') or '').strip()


def _headers() -> dict[str, str]:
    key = fal_key()
    if not key:
        raise MediaError('the fal key is not configured')
    return {'Authorization': f'Key {key}', 'Content-Type': 'application/json',
            'Accept': 'application/json'}


def _request(url: str, method: str = 'GET', payload: dict | None = None,
             timeout: int = 60) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(url, headers=_headers(), method=method, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', 'replace')
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', 'replace')[:300]
        raise MediaError(f'provider error {error.code}: {detail}') from error
    except Exception as exc:
        raise MediaError(f'provider call failed: {exc}') from exc


def _download(url: str, timeout: int = 120) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        raise MediaError(f'cannot download the result: {exc}') from exc


def _queue_audio(model: str, path: Path) -> tuple[str, str]:
    """Send an audio file to the provider and return the urls to watch.

    The provider takes the file as a data uri in the body of the request,
    so the file never needs a place of its own.
    """
    mime = mimetypes.guess_type(path.name)[0] or 'audio/mpeg'
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    payload = {'audio_url': f'data:{mime};base64,{encoded}'}
    status_url, response_url = _queue(model, payload)
    return status_url, response_url


def _await(status_url: str, response_url: str, timeout: int) -> dict[str, Any]:
    """Wait for a queued request of the provider and return the answer."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = _request(status_url).get('status')
        if state == 'COMPLETED':
            return _request(response_url)
        if state in ('FAILED', 'CANCELLED'):
            raise MediaError(f'the provider reported {str(state).lower()}')
        time.sleep(2)
    raise MediaError('the provider did not finish in time')


def _queue(model: str, payload: dict[str, Any]) -> tuple[str, str]:
    """Send a request to the queue and return the urls to watch."""
    base = f'{FAL_QUEUE}/{model}'
    first = _request(base, 'POST', payload)
    request_id = first.get('request_id')
    if not request_id:
        raise MediaError('the provider returned no request id')
    status_url = first.get('status_url') or f'{base}/requests/{request_id}/status'
    response_url = first.get('response_url') or f'{base}/requests/{request_id}'
    return status_url, response_url


def _queue_is_closed(error: Exception) -> bool:
    """Tell whether the queue is closed for lack of money.

    The queue of fal closes the account when the money is gone. That is not
    a broken call but a closed road, so the core takes the other one.
    """
    text = str(error).lower()
    return 'exhausted balance' in text or 'user is locked' in text


def _queue_is_open() -> bool:
    """Tell whether the queue of fal can be used at all."""
    return bool(fal_key())


def music(workspace: Path, lyrics: str, prompt: str, filename: str = 'music.mp3') -> dict[str, Any]:
    """Write a song with a voice over a production.

    The queue of fal is the only road for a song. When it is closed for
    lack of money, the agent is told so instead of being given a broken
    file.
    """
    text = str(lyrics or '').strip()
    style = str(prompt or '').strip()
    if not text or not style:
        raise MediaError('both the lyrics and the production are required')
    if text == style:
        raise MediaError('the lyrics and the production must not be the same text')
    tags = {'[verse]': '[Verse]', '[pre-chorus]': '[Pre Chorus]', '[pre chorus]': '[Pre Chorus]',
            '[chorus]': '[Chorus]', '[bridge]': '[Bridge]', '[outro]': '[Outro]',
            '[intro]': '[Intro]', '[hook]': '[Hook]', '[inst]': '[Inst]', '[solo]': '[Solo]'}
    for old, new in tags.items():
        text = text.replace(old, new).replace(old.lower(), new)
    if not _queue_is_open():
        raise MediaError('the music provider is closed for now, it is topped up later')
    try:
        status_url, response_url = _queue(MUSIC_MODEL, {'prompt': style[:2000], 'lyrics': text[:3500]})
        answer = _await(status_url, response_url, MUSIC_TIMEOUT)
    except MediaError as error:
        if not _queue_is_closed(error):
            raise
        raise MediaError(
            'the music provider is closed for now, it is topped up later') from error
    audio = answer.get('audio') or answer.get('audio_file')
    url = audio.get('url') if isinstance(audio, dict) else audio
    if not url:
        raise MediaError('the provider returned no audio')
    content = _download(str(url))
    name = Path(filename or 'music.mp3').name
    target = workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {'path': name, 'size_bytes': len(content), 'mime': 'audio/mpeg'}


def transcribe(workspace: Path, source: str, filename: str = 'transcript.txt') -> dict[str, Any]:
    """Write the words of an audio file.

    The queue of fal is the first road. When it is closed for lack of
    money, the provider of the core reads the file instead.
    """
    path = Path(source)
    if not path.is_file():
        raise MediaError(f'not a file: {source!r}')
    try:
        status_url, response_url = _queue_audio(TRANSCRIBE_MODEL, path)
        answer = _await(status_url, response_url, MUSIC_TIMEOUT)
    except MediaError as error:
        if _queue_is_open() and not _queue_is_closed(error):
            raise
        from .voice import VoiceError, transcribe as core_transcribe
        try:
            return core_transcribe(workspace, str(path), filename)
        except VoiceError as other:
            raise MediaError(str(other)) from other
    text = str(answer.get('text') or answer.get('transcription') or '').strip()
    if not text:
        raise MediaError('the provider returned no text')
    name = Path(filename or 'transcript.txt').name
    target = workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    return {'path': name, 'text': text, 'size_bytes': len(text.encode('utf-8'))}


def speak(workspace: Path, text: str, voice: str = '', filename: str = 'speech.mp3') -> dict[str, Any]:
    """Read a text out loud.

    The queue of fal is the first road. When it is closed for lack of
    money, the provider of the core speaks instead.
    """
    words = str(text or '').strip()
    if not words:
        raise MediaError('there is no text to read')
    payload: dict[str, Any] = {'text': words}
    if voice:
        payload['voice'] = str(voice)
    try:
        status_url, response_url = _queue(SPEECH_MODEL, payload)
        answer = _await(status_url, response_url, MUSIC_TIMEOUT)
    except MediaError as error:
        if _queue_is_open() and not _queue_is_closed(error):
            raise
        from .voice import VoiceError, speak as core_speak
        try:
            return core_speak(workspace, words, filename, voice or 'alloy')
        except VoiceError as other:
            raise MediaError(str(other)) from other
    audio = answer.get('audio') or {}
    url = audio.get('url') if isinstance(audio, dict) else audio
    if not url:
        raise MediaError('the provider returned no audio')
    content = _download(str(url))
    name = Path(filename or 'speech.mp3').name
    target = workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {'path': name, 'size_bytes': len(content), 'mime': 'audio/mpeg'}


def ffmpeg() -> str:
    """The ffmpeg binary of the system."""
    path = shutil.which('ffmpeg')
    if not path:
        raise MediaError('ffmpeg is not installed')
    return path


def ffprobe() -> str:
    path = shutil.which('ffprobe')
    if not path:
        raise MediaError('ffprobe is not installed')
    return path


def export_video(workspace: Path, source: str, filename: str = 'video.mp4') -> dict[str, Any]:
    """Make a web ready copy of a video."""
    path = Path(source)
    if not path.is_file():
        raise MediaError(f'not a file: {source!r}')
    name = Path(filename or 'video.mp4').name
    target = workspace / name
    command = [
        ffmpeg(), '-y', '-i', str(path),
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
        str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise MediaError('the video export took too long') from exc
    if result.returncode != 0 or not target.is_file():
        raise MediaError(f'the video export failed: {result.stderr[-300:]}')
    duration = 0.0
    try:
        probe = subprocess.run(
            [ffprobe(), '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(target)],
            capture_output=True, text=True, timeout=60)
        duration = round(float(probe.stdout.strip() or 0), 2)
    except Exception:
        duration = 0.0
    return {'path': name, 'size_bytes': target.stat().st_size,
            'mime': 'video/mp4', 'duration': duration}
