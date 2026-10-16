"""One provider adapter; different compatible API endpoints are configuration."""

from __future__ import annotations

from hermes.config import Config

from .base import LLMProvider
from .openai_compatible import OpenAICompatibleProvider


def get_provider(config: Config) -> LLMProvider:
    return OpenAICompatibleProvider(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
    )
