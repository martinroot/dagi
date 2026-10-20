"""Media tools for the Dagi core.

The Fabra agents draw and edit pictures, and the core had no counterpart: an
agent that needed a picture had a tool gap and could not be shipped to the
site.

The pictures come from the OpenRouter provider of the core, the same key and
the same account the model calls use. The result is written into the session
workspace, so the core keeps the file, the artifact and the cost.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
DEFAULT_IMAGE_MODEL = 'openai/gpt-5-image-mini'
DEFAULT_COST_USD = 0.04
MAX_BATCH = 20


class MediaError(Exception):
    """A provider call that did not work."""


def api_key() -> str:
    return (os.getenv('DAGI_API_KEY') or os.getenv('OPENROUTER_API_KEY') or '').strip()


def base_url() -> str:
    return (os.getenv('DAGI_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')


def image_model() -> str:
    return (os.getenv('DAGI_IMAGE_MODEL') or DEFAULT_IMAGE_MODEL).strip()


def _post(body: dict[str, Any], timeout: int = 240) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise MediaError('the provider key is not configured')
    request = urllib.request.Request(
        f'{base_url()}/chat/completions',
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': os.getenv('OPENROUTER_SITE_URL') or 'https://fabra.live',
            'X-Title': os.getenv('OPENROUTER_APP_NAME') or 'Fabra',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', 'replace')
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', 'replace')[:400]
        raise MediaError(f'provider error {error.code}: {detail}') from error
    except Exception as exc:
        raise MediaError(f'provider call failed: {exc}') from exc


def _image_bytes(data: dict[str, Any]) -> tuple[bytes, str]:
    """Take the image out of the answer of the provider."""
    choices = data.get('choices') or []
    if not choices:
        raise MediaError('the provider returned no answer')
    message = choices[0].get('message') or {}
    images = message.get('images') or []
    for image in images:
        url = str((image or {}).get('image_url', {}).get('url') or '')
        if url.startswith('data:'):
            header, _, payload = url.partition(',')
            mime = header[5:].split(';')[0] or 'image/png'
            try:
                return base64.b64decode(payload), mime
            except Exception as exc:
                raise MediaError(f'cannot decode the image: {exc}') from exc
        if url:
            return _download(url)
    raise MediaError('the provider returned no image')


def _download(url: str, timeout: int = 120) -> tuple[bytes, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            content_type = response.headers.get('content-type') or 'image/png'
            return response.read(), content_type
    except Exception as exc:
        raise MediaError(f'cannot download the result: {exc}') from exc


def _save(workspace: Path, data: dict[str, Any], filename: str) -> dict[str, Any]:
    content, mime = _image_bytes(data)
    extension = mimetypes.guess_extension(mime.split(';')[0]) or '.png'
    name = Path(filename or 'image-result').stem + extension
    target = workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    usage = data.get('usage') or {}
    cost = float(usage.get('cost') or 0) or DEFAULT_COST_USD
    return {
        'path': name,
        'mime': mime,
        'size_bytes': len(content),
        'cost_usd': round(cost, 6),
        'model': str(data.get('model') or image_model()),
    }


def _content(prompt: str, images: list[str] | None = None) -> list[dict[str, Any]]:
    """Build the content of the message, with the source images if there are any."""
    if not images:
        return [{'type': 'text', 'text': prompt}]
    parts: list[dict[str, Any]] = [{'type': 'text', 'text': prompt}]
    for item in images:
        parts.append({'type': 'image_url', 'image_url': {'url': item}})
    return parts


def generate(workspace: Path, prompt: str, filename: str = 'generated.jpg',
             aspect_ratio: str = '') -> dict[str, Any]:
    """Draw a new image from a prompt."""
    text = str(prompt or '').strip()
    if not text:
        raise MediaError('a prompt is required')
    body = {
        'model': image_model(),
        'messages': [{'role': 'user', 'content': _content(text)}],
        'modalities': ['image', 'text'],
    }
    if aspect_ratio:
        body['aspect_ratio'] = str(aspect_ratio)
    return _save(workspace, _post(body), filename)


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or 'image/jpeg'
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{encoded}'


def edit(workspace: Path, source: str, prompt: str, filename: str = 'edited.jpg',
         aspect_ratio: str = '') -> dict[str, Any]:
    """Change an existing image with a prompt."""
    path = Path(source)
    if not path.is_file():
        raise MediaError(f'not a file: {source!r}')
    text = str(prompt or '').strip()
    if not text:
        raise MediaError('a prompt is required')
    body = {
        'model': image_model(),
        'messages': [{'role': 'user', 'content': _content(text, [_data_uri(path)])}],
        'modalities': ['image', 'text'],
    }
    if aspect_ratio:
        body['aspect_ratio'] = str(aspect_ratio)
    return _save(workspace, _post(body), filename)


def edit_batch(workspace: Path, sources: list[str], prompt: str,
               filename_prefix: str = 'result') -> dict[str, Any]:
    """Change several images with the same prompt."""
    items = [str(item) for item in (sources or [])][:MAX_BATCH]
    text = str(prompt or '').strip()
    if not items:
        raise MediaError('at least one input file is required')
    if not text:
        raise MediaError('a prompt is required')
    prefix = ''.join(
        character if character.isalnum() or character in '-_' else '-'
        for character in str(filename_prefix or 'result')
    ).strip('-') or 'result'
    results: list[dict[str, Any]] = []
    for index, relative in enumerate(items, 1):
        path = Path(relative)
        if not path.is_file():
            continue
        body = {
            'model': image_model(),
            'messages': [{'role': 'user', 'content': _content(text, [_data_uri(path)])}],
            'modalities': ['image', 'text'],
        }
        results.append(_save(workspace, _post(body), f'{prefix}-{index:02d}.jpg'))
    if not results:
        raise MediaError('the batch produced no images')
    bundle = workspace / f'{prefix}-results.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in results:
            path = workspace / str(item['path'])
            if path.is_file():
                archive.write(path, path.name)
    total = round(sum(float(item['cost_usd']) for item in results), 6)
    return {'items': results, 'path': bundle.name, 'cost_usd': total}
