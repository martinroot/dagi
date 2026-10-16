from decimal import Decimal

import pytest

from dagi_core.state import StateStore
from dagi_core.usage import ModelPrice, UsagePolicy


def test_usage_policy_labels_estimates_and_computes_decimal_cost():
    policy = UsagePolicy(
        prices={"test-model": ModelPrice(Decimal("1.00"), Decimal("2.00"))},
        max_calls_per_run=4,
    )

    messages = [{"role": "user", "content": "four words"}]
    sample = policy.measure(
        "test-model", messages, "a short answer", actual_usage=None,
    )
    with_tool_schema = policy.measure(
        "test-model", messages, "a short answer", actual_usage=None,
        tools=[{"name": "a_tool", "description": "x" * 200}],
    )

    assert sample.source == "estimated"
    assert with_tool_schema.input_tokens > sample.input_tokens
    assert sample.input_tokens > 0
    assert sample.output_tokens > 0
    assert sample.cost_usd == (
        Decimal(sample.input_tokens) * Decimal("1.00")
        + Decimal(sample.output_tokens) * Decimal("2.00")
    ) / Decimal(1_000_000)


def test_usage_policy_preserves_actual_and_unavailable_as_different_states():
    policy = UsagePolicy()
    actual = policy.measure(
        "unpriced",
        [{"role": "user", "content": "question"}],
        "answer",
        actual_usage={"input_tokens": 12, "output_tokens": 3},
    )
    unavailable = policy.measure(
        "unpriced", [{"role": "user", "content": "question"}], "", actual_usage=None,
        estimate=False,
    )

    assert (actual.source, actual.input_tokens, actual.output_tokens, actual.cost_usd) == (
        "actual", 12, 3, None
    )
    assert (unavailable.source, unavailable.input_tokens, unavailable.output_tokens, unavailable.cost_usd) == (
        "unavailable", None, None, None
    )


def test_run_usage_aggregates_calls_but_never_sums_missing_data_as_zero(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    run = state.create_run(session)
    actual = state.create_provider_call(run, "model-a", "primary")
    state.record_usage(actual, {
        "source": "actual", "input_tokens": 100, "output_tokens": 20, "cost_usd": "0.001",
    })
    estimated = state.create_provider_call(run, "model-a", "compression")
    state.record_usage(estimated, {
        "source": "estimated", "input_tokens": 50, "output_tokens": 10, "cost_usd": "0.0005",
    })

    known = state.usage_summary(run)
    assert known["provider_calls"] == 2
    assert known["source"] == "mixed"
    assert (known["input_tokens"], known["output_tokens"]) == (150, 30)
    assert known["cost_usd"] == Decimal("0.0015")

    missing = state.create_provider_call(run, "unknown-model", "retry")
    with pytest.raises(ValueError, match="unavailable usage"):
        state.record_usage(missing, {
            "source": "unavailable", "input_tokens": 0, "output_tokens": 0, "cost_usd": "0",
        })
    state.record_usage(missing, {
        "source": "unavailable", "input_tokens": None, "output_tokens": None, "cost_usd": None,
    })
    summary = state.usage_summary(run)

    assert summary["provider_calls"] == 3
    assert summary["source"] == "unavailable"
    assert summary["input_tokens"] is None
    assert summary["output_tokens"] is None
    assert summary["cost_usd"] is None
    assert {item["purpose"] for item in state.list_provider_calls(run)} == {
        "primary", "compression", "retry"
    }
    state.close()


def test_budget_policy_blocks_unknown_cost_and_exhausted_call_budget():
    policy = UsagePolicy(
        prices={"model-a": ModelPrice(Decimal("1"), Decimal("1"))},
        max_calls_per_run=2,
        budget_usd=Decimal("0.01"),
    )
    assert policy.stop_reason({"provider_calls": 0, "cost_usd": Decimal("0")}) is None
    assert "call" in policy.stop_reason({"provider_calls": 2, "cost_usd": Decimal("0")})
    assert "unknown" in policy.stop_reason({"provider_calls": 1, "cost_usd": None})
    assert "budget" in policy.stop_reason({"provider_calls": 1, "cost_usd": Decimal("0.01")})


def test_agent_persists_actual_usage_and_enforces_provider_call_limit(tmp_path):
    from dagi_core.agent import Agent
    from dagi_core.provider import StreamEvent
    from dagi_core.tools import ToolRegistry

    class Provider:
        model = "test-model"

        def __init__(self):
            self.calls = 0

        def stream(self, *_args):
            self.calls += 1
            return iter([
                StreamEvent(kind="tool_call", tool_call={"id": "call-1", "name": "unknown", "arguments": {}}),
                StreamEvent(kind="usage", usage={"input_tokens": 100, "output_tokens": 20}),
                StreamEvent(kind="finish", finish_reason="tool_calls"),
            ])

    policy = UsagePolicy(max_calls_per_run=1)
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    provider = Provider()
    tools = ToolRegistry(tmp_path / "workspace", state, session)

    events = list(Agent(provider, tools, state, session, usage_policy=policy).run_turn("loop"))

    summary = state.usage_summary(events[-1].run_id)
    assert provider.calls == 1
    assert summary["provider_calls"] == 1
    assert summary["source"] == "actual"
    assert summary["input_tokens"] == 100
    assert events[-1].status == "limit"
    state.close()


def test_unknown_usage_with_money_budget_stops_before_tool_effect(tmp_path):
    from dagi_core.agent import Agent
    from dagi_core.provider import StreamEvent
    from dagi_core.tools import ToolRegistry

    class Provider:
        model = "priced-model"

        def stream(self, *_args):
            return iter([
                StreamEvent(kind="tool_call", tool_call={
                    "id": "call-unknown-usage", "name": "write_file",
                    "arguments": {"path": "should-not-exist", "content": "unsafe"},
                }),
                StreamEvent(kind="finish", finish_reason="tool_calls"),
            ])

    policy = UsagePolicy(
        prices={"priced-model": ModelPrice(Decimal("1"), Decimal("1"))},
        max_calls_per_run=4, budget_usd=Decimal("0.01"), estimate_missing=False,
    )
    state = StateStore(tmp_path / "state.sqlite3")
    session = state.create_session()
    workspace = tmp_path / "workspace"
    tools = ToolRegistry(workspace, state, session)

    events = list(Agent(Provider(), tools, state, session, usage_policy=policy).run_turn("write"))

    assert not (workspace / "should-not-exist").exists()
    summary = state.usage_summary(events[-1].run_id)
    assert summary["source"] == "unavailable"
    assert summary["cost_usd"] is None
    assert events[-1].status == "limit"
    state.close()
