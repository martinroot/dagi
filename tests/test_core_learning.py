"""Core-owned skill contracts: bounded expressions, measurable criteria, mastery.

The game package used to own this machinery. It is domain neutral: a contract
describes measurable criteria, a host supplies measured reports, and mastery is
granted only when every case, target and prerequisite holds.
"""
import math

from dagi_core.expressions import evaluate, parse
from dagi_core.learning import (
    ContractError,
    grade_report,
    plan_contracts,
    progress,
    skill_statuses,
    validate_contract,
)


def _contract(**overrides):
    contract = {
        "id": "balance",
        "title": "Balance",
        "depends": [],
        "program": "balance_controller",
        "metrics": [
            {"name": "upright_ratio", "expression": "s['upright']", "reduce": "mean", "target": {"min": 0.5}},
        ],
        "score": "r['metrics']['upright_ratio']",
        "success": "r['metrics']['upright_ratio'] >= 0.5",
        "guards": ["r['external_supports'] == 0"],
        "cases": [
            {"id": "train-1", "frames": 120, "start": "neutral", "split": "train"},
            {"id": "valid-1", "frames": 120, "start": "neutral", "split": "validation"},
        ],
    }
    contract.update(overrides)
    return contract


def _report(**overrides):
    report = {
        "passed": True,
        "metrics": {"upright_ratio": 0.8},
        "external_supports": 0,
    }
    report.update(overrides)
    return report


def test_bounded_expressions_reject_host_access():
    for source in ("__import__('os').system('id')", "open('/etc/passwd').read()", "[].__class__"):
        try:
            evaluate(source, {"s": {}})
        except ValueError:
            continue
        raise AssertionError(f"expression must be rejected: {source}")


def test_bounded_expressions_evaluate_metrics_and_guards():
    assert evaluate("s['upright']", {"s": {"upright": 1}}) == 1
    assert evaluate("r['metrics']['x'] >= 0.5", {"r": {"metrics": {"x": 0.6}}}) is True
    assert evaluate("min(1, 2) + 1", {}) == 2


def test_contract_validation_requires_explicit_criteria():
    try:
        validate_contract(_contract(metrics=[]))
    except ContractError as error:
        assert "metric" in str(error)
    else:
        raise AssertionError("a contract without metrics must be rejected")

    try:
        validate_contract(_contract(cases=[{"id": "only-train", "frames": 120, "start": "neutral", "split": "train"}]))
    except ContractError as error:
        assert "validation" in str(error)
    else:
        raise AssertionError("a contract without a validation case must be rejected")


def test_contract_validation_rejects_cycles_and_unknown_prerequisites():
    try:
        plan_contracts(
            {
                "goal": "walk",
                "target": "a",
                "reason": "decompose the goal",
                "skills": [
                    _contract(id="a", depends=["b"]),
                    _contract(id="b", depends=["a"]),
                ],
            }
        )
    except ContractError as error:
        assert "cycle" in str(error)
    else:
        raise AssertionError("a dependency cycle must be rejected")

    try:
        plan_contracts({"goal": "walk", "reason": "decompose", "target": "a", "skills": [_contract(id="a", depends=["ghost"])]})
    except ContractError as error:
        assert "prerequisite" in str(error)
    else:
        raise AssertionError("an unknown prerequisite must be rejected")


def test_grading_uses_measured_values_not_claims():
    contract = validate_contract(_contract())
    graded = grade_report(contract, _report())
    assert graded["passed"] is True
    assert graded["score"] == 0.8
    assert graded["metrics"][0]["metric"] == "upright_ratio"
    assert graded["metrics"][0]["passed"] is True

    failed = grade_report(contract, _report(metrics={"upright_ratio": 0.1}))
    assert failed["passed"] is False
    assert failed["metrics"][0]["passed"] is False

    guarded = grade_report(contract, _report(external_supports=1))
    assert guarded["passed"] is False
    assert guarded["guards_pass"] is False


def test_mastery_requires_measured_evidence_and_mastered_prerequisites():
    contracts = {
        "balance": validate_contract(_contract()),
        "walk": validate_contract(_contract(id="walk", title="Walk", depends=["balance"])),
    }
    attempts = {
        "balance": [{"id": "a1", "contract": contracts["balance"]["version"], "passed": True, "score": 0.8, "applied": True, "binding": "b1"}],
        "walk": [{"id": "w1", "contract": contracts["walk"]["version"], "passed": True, "score": 0.9, "applied": True, "binding": "b2"}],
    }
    bindings = {"balance": "b1", "walk": "b2"}
    statuses = skill_statuses(contracts, attempts, bindings)
    assert statuses["balance"]["status"] == "mastered"
    assert statuses["walk"]["status"] == "mastered", "a mastered prerequisite unlocks the dependent skill"

    attempts["balance"] = []
    statuses = skill_statuses(contracts, attempts, bindings)
    assert statuses["balance"]["status"] == "ready"
    assert statuses["walk"]["status"] == "blocked"
    assert "balance" in (statuses["walk"]["reason"] or "")


def test_an_unapplied_experiment_never_grants_mastery():
    contract = validate_contract(_contract())
    attempts = {"balance": [{"id": "x1", "contract": contract["version"], "passed": True, "score": 0.9, "applied": False, "binding": "b1"}]}
    statuses = skill_statuses({"balance": contract}, attempts, {"balance": "b1"})
    assert statuses["balance"]["status"] != "mastered"


def test_a_changed_binding_expires_the_previous_certificate():
    contract = validate_contract(_contract())
    attempts = {"balance": [{"id": "x1", "contract": contract["version"], "passed": True, "score": 0.9, "applied": True, "binding": "b1"}]}
    assert skill_statuses({"balance": contract}, attempts, {"balance": "b1"})["balance"]["status"] == "mastered"
    assert skill_statuses({"balance": contract}, attempts, {"balance": "b2"})["balance"]["status"] != "mastered"


def test_publish_progress_requires_a_guarded_improvement():
    before = {"passed": False, "guards_pass": True, "score": 0.4, "cases": [{"id": "valid-1", "split": "validation", "score": 0.4}]}
    after = {"passed": False, "guards_pass": True, "score": 0.6, "cases": [{"id": "valid-1", "split": "validation", "score": 0.6}]}
    accepted, improved = progress(before, after, 0.01)
    assert improved is True
    assert accepted is True

    regressed = {"passed": False, "guards_pass": True, "score": 0.2, "cases": [{"id": "valid-1", "split": "validation", "score": 0.2}]}
    accepted, improved = progress(before, regressed, 0.01)
    assert improved is False
    assert accepted is False
