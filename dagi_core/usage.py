"""Token provenance, exact Decimal pricing, and per-run call/budget policy."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

UsageSource = Literal["actual", "estimated", "unavailable"]


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self) -> None:
        for value in (self.input_per_million, self.output_per_million):
            if not value.is_finite() or value < 0:
                raise ValueError("model prices must be finite and non-negative")


@dataclass(frozen=True)
class UsageRecord:
    source: UsageSource
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": str(self.cost_usd) if self.cost_usd is not None else None,
        }


@dataclass(frozen=True)
class UsagePolicy:
    prices: dict[str, ModelPrice] = field(default_factory=dict)
    max_calls_per_run: int = 32
    budget_usd: Decimal | None = None
    estimate_missing: bool = True

    def __post_init__(self) -> None:
        if self.max_calls_per_run < 1:
            raise ValueError("max provider calls per run must be at least 1")
        if self.budget_usd is not None and (
            not self.budget_usd.is_finite() or self.budget_usd <= 0
        ):
            raise ValueError("DAGI_BUDGET_USD must be finite and greater than 0")

    def validate_model(self, model: str) -> None:
        if self.budget_usd is not None and model not in self.prices:
            raise ValueError(f"a price for model {model!r} is required when a money budget is set")

    def measure(
        self,
        model: str,
        messages: list[dict[str, Any]],
        response_text: str,
        actual_usage: dict[str, Any] | None,
        *,
        tools: list[dict[str, Any]] | None = None,
        estimate: bool | None = None,
    ) -> UsageRecord:
        input_tokens = _valid_token_count(actual_usage.get("input_tokens")) if actual_usage else None
        output_tokens = _valid_token_count(actual_usage.get("output_tokens")) if actual_usage else None
        should_estimate = self.estimate_missing if estimate is None else estimate
        if input_tokens is not None and output_tokens is not None:
            source: UsageSource = "actual"
        elif should_estimate:
            serialized = json.dumps(
                {"messages": messages, "tools": tools},
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            input_tokens = _estimate_tokens(serialized)
            output_tokens = _estimate_tokens(response_text)
            source = "estimated"
        else:
            return UsageRecord("unavailable", None, None, None)

        price = self.prices.get(model)
        cost = None
        if price is not None:
            cost = (
                Decimal(input_tokens) * price.input_per_million
                + Decimal(output_tokens) * price.output_per_million
            ) / Decimal(1_000_000)
        return UsageRecord(source, input_tokens, output_tokens, cost)

    def stop_reason(self, summary: dict[str, Any]) -> str | None:
        calls = int(summary.get("provider_calls", 0))
        if calls >= self.max_calls_per_run:
            return f"provider call limit reached ({self.max_calls_per_run})"
        if self.budget_usd is None or calls == 0:
            return None
        cost = summary.get("cost_usd")
        if cost is None:
            return "usage is unknown; the monetary budget cannot be enforced"
        if Decimal(cost) >= self.budget_usd:
            return f"monetary budget reached ({self.budget_usd} USD)"
        return None


def _valid_token_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))
