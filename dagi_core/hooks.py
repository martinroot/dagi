"""Constructor-registered lifecycle hooks for the agent loop.

Hooks are in-process callbacks only: there is no route, tool, or persisted
configuration that can register them. A hook denies an operation by raising;
the dispatcher turns that into a bounded error string for the run transcript.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .tools import ToolResult

BeforeModel = Callable[[dict[str, Any]], None]
BeforeTool = Callable[[str, dict[str, Any]], None]
AfterTool = Callable[[str, dict[str, Any], ToolResult], None]


@dataclass(frozen=True)
class LifecycleHooks:
    before_model: BeforeModel | None = None
    before_tool: BeforeTool | None = None
    after_tool: AfterTool | None = None

    def __post_init__(self) -> None:
        for name in ("before_model", "before_tool", "after_tool"):
            hook = getattr(self, name)
            if hook is not None and not callable(hook):
                raise ValueError(f"{name} must be callable or None")

    def invoke(self, name: str, *args: Any) -> str | None:
        """Return a bounded denial reason, or None when the hook allows the step."""
        hook = getattr(self, name, None)
        if hook is None:
            return None
        try:
            hook(*args)
        except Exception as exc:
            message = str(exc).replace("\n", " ")[:200]
            return f"{type(exc).__name__}: {message}"
        return None
