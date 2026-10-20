from decimal import Decimal
from pathlib import Path

from dagi_core.state import StateStore
from dagi_core.usage import ModelPrice


def _store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state.sqlite3")


def _record(store: StateStore, run_id: str, model: str, cost_usd: str | None) -> None:
    call_id = store.create_provider_call(run_id, model, "chat")
    store.record_usage(call_id, {
        "source": "actual",
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": cost_usd,
    })


def test_cost_status_distinguishes_priced_and_unavailable(tmp_path: Path):
    store = _store(tmp_path)
    prices = {"model-a": ModelPrice(Decimal("1"), Decimal("2"))}
    session_id = store.create_session("cost")
    run_id = store.create_run(session_id, agent_name="a", agent_id="a")
    _record(store, run_id, "model-a", "0.01")
    status = store.cost_status(run_id, prices)
    assert status["status"] == "priced"
    assert status["unpriced_models"] == []
    assert status["priced_models"] == ["model-a"]
    assert status["cost_usd"] is not None

    _record(store, run_id, "model-b", None)
    status = store.cost_status(run_id, prices)
    assert status["status"] == "partial"
    assert status["unpriced_models"] == ["model-b"]
    assert status["cost_usd"] is None
    assert "DAGI_MODEL_PRICES" in status["explanation"]
    assert "model-b" in status["explanation"]


def test_cost_status_is_unavailable_when_no_model_is_priced(tmp_path: Path):
    store = _store(tmp_path)
    session_id = store.create_session("unpriced")
    run_id = store.create_run(session_id, agent_name="a", agent_id="a")
    _record(store, run_id, "model-b", None)
    status = store.cost_status(run_id, {"model-a": ModelPrice(Decimal("1"), Decimal("2"))})
    assert status["status"] == "unavailable"
    assert status["unpriced_models"] == ["model-b"]
    assert status["cost_usd"] is None
    assert "model-b" in status["explanation"]


def test_cost_status_reports_partially_priced_run(tmp_path: Path):
    store = _store(tmp_path)
    prices = {"model-a": ModelPrice(Decimal("1"), Decimal("2"))}
    session_id = store.create_session("mixed")
    run_id = store.create_run(session_id, agent_name="a", agent_id="a")
    _record(store, run_id, "model-a", "0.02")
    _record(store, run_id, "model-b", None)
    status = store.cost_status(run_id, prices)
    assert status["status"] == "partial"
    assert status["unpriced_models"] == ["model-b"]
    assert status["priced_models"] == ["model-a"]
    assert status["cost_usd"] is None
    assert "model-b" in status["explanation"]


def test_cost_status_of_empty_run_is_unknown_not_zero(tmp_path: Path):
    store = _store(tmp_path)
    session_id = store.create_session("empty")
    run_id = store.create_run(session_id, agent_name="a", agent_id="a")
    status = store.cost_status(run_id, {})
    assert status["status"] == "unknown"
    assert status["cost_usd"] is None
    assert status["explanation"]


def test_cost_status_group_covers_child_runs(tmp_path: Path):
    store = _store(tmp_path)
    prices = {"model-a": ModelPrice(Decimal("1"), Decimal("2"))}
    parent_session = store.create_session("parent")
    parent_id = store.create_run(parent_session, agent_name="parent", agent_id="p")
    child_session = store.create_session("child", parent_id=parent_session)
    child_id = store.create_run(
        child_session, agent_id="c", agent_name="child",
        parent_run_id=parent_id, budget_group_id=parent_id,
    )
    _record(store, parent_id, "model-a", "0.02")
    _record(store, child_id, "model-b", None)
    group = store.cost_status(parent_id, prices, group=True)
    assert group["status"] == "partial"
    assert group["unpriced_models"] == ["model-b"]
    assert group["priced_models"] == ["model-a"]
