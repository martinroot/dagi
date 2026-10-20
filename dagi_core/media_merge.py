"""Merge two pictures with a prompt.

The Fabra agent that combines two pictures has no counterpart in the core.
The merge is a generation with both pictures as the input of the model, so
the result is a new picture that holds what the prompt asked for.
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

DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
DEFAULT_IMAGE_MODEL = 'openai/gpt-5-image-mini'
DEFAULT_COST_USD = 0.04


class MergeError(Exception):
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
        raise MergeError('the provider key is not configured')
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
        raise MergeError(f'provider error {error.code}: {detail}') from error
    except Exception as exc:
        raise MergeError(f'provider call failed: {exc}') from exc


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or 'image/jpeg'
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{encoded}'


def merge(workspace: Path, first: str, second: str, prompt: str,
          filename: str = 'merged.png') -> dict[str, Any]:
    """Combine two pictures into one new picture."""
    left = Path(first)
    right = Path(second)
    for path in (left, right):
        if not path.is_file():
            raise MergeError(f'not a file: {path.name!r}')
    text = str(prompt or '').strip()
    if not text:
        raise MergeError('a prompt is required')
    body = {
        'model': image_model(),
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': text},
            {'type': 'image_url', 'image_url': {'url': _data_uri(left)}},
            {'type': 'image_url', 'image_url': {'url': _data_uri(right)}},
        ]}],
        'modalities': ['image', 'text'],
    }
    data = _post(body)
    choices = data.get('choices') or []
    if not choices:
        raise MergeError('the provider returned no answer')
    images = (choices[0].get('message') or {}).get('images') or []
    for image in images:
        url = str((image or {}).get('image_url', {}).get('url') or '')
        if not url.startswith('data:'):
            continue
        _, _, payload = url.partition(',')
        try:
            content = base64.b64decode(payload)
        except Exception as exc:
            raise MergeError(f'cannot decode the image: {exc}') from exc
        name = Path(filename or 'merged.png').name
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        usage = data.get('usage') or {}
        cost = float(usage.get('cost') or 0) or DEFAULT_COST_USD
        return {
            'path': name,
            'size_bytes': len(content),
            'mime': 'image/png',
            'cost_usd': round(cost, 6),
            'model': str(data.get('model') or image_model()),
        }
    raise MergeError('the provider returned no image')
