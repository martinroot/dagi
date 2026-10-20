"""Video generation for the Dagi core.

The Fabra agent that turns a photo into a short video needs a video
provider, and the core had no counterpart. The provider is the queue of fal:
the picture goes in as a data uri and the video comes back as a file.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .media_audio import FAL_QUEUE, MediaError, _await, _download, _queue, _queue_is_closed, fal_key

VIDEO_MODEL = 'fal-ai/kling-video/v1/standard/image-to-video'
VIDEO_TIMEOUT = 600


def video_model() -> str:
    return (os.getenv('DAGI_VIDEO_MODEL') or VIDEO_MODEL).strip()


def generate_video(workspace: Path, source: str, prompt: str,
                    filename: str = 'video.mp4', duration: str = '5') -> dict[str, Any]:
    """Turn a picture into a short video."""
    path = Path(source)
    if not path.is_file():
        raise MediaError(f'not a file: {source!r}')
    text = str(prompt or '').strip()
    if not text:
        raise MediaError('a prompt is required')
    mime = mimetypes.guess_type(path.name)[0] or 'image/png'
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    payload = {
        'prompt': text,
        'image_url': f'data:{mime};base64,{encoded}',
    }
    if duration:
        payload['duration'] = str(duration)
    model = video_model()
    try:
        status_url, response_url = _queue(model, payload)
        answer = _await(status_url, response_url, VIDEO_TIMEOUT)
    except MediaError as error:
        if not _queue_is_closed(error):
            raise
        raise MediaError(
            'the video provider is closed for now, it is topped up later') from error
    video = answer.get('video') or {}
    url = video.get('url') if isinstance(video, dict) else video
    if not url:
        raise MediaError('the provider returned no video')
    content = _download(str(url), timeout=300)
    name = Path(filename or 'video.mp4').name
    target = workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {
        'path': name,
        'size_bytes': len(content),
        'mime': 'video/mp4',
        'model': model,
    }
