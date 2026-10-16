"""Provider-agnostic chat/tool-calling interface.

The agent loop depends on these shared dataclasses and never touches a provider SDK directly. A compatible API adapter can implement `LLMProvider.stream`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class StreamChunk:
    """One incremental unit of an assistant turn."""

    kind: Literal["text_delta", "tool_call", "usage", "done"]
    text: str | None = None
    tool_call: ToolCall | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMProvider(ABC):
    """Abstract chat-completion + tool-calling backend."""

    def __init__(self, model: str, api_key: str | None):
        self.model = model
        self.api_key = api_key

    @abstractmethod
    def stream(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Iterator[StreamChunk]:
        """Stream one assistant turn given full conversation history."""
        raise NotImplementedError
