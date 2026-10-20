"""Skill fitness contracts: measurable criteria, receipts, and honest mastery.

A successful tool call is never a skill certificate. A contract names the
metrics, the score, the success predicate and the guards; a host supplies
measured reports; a receipt is only a certificate while its contract version
and its binding are unchanged. Mastery additionally requires every mastered
prerequisite, so a child skill cannot certify its parent.

The game package used to own this machinery. It is domain neutral: physics
supplies reports today, and file, test or deployment hosts can reuse it as
long as they obtain their own trusted measurements.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

from dagi_core.expressions import evaluate, parse

REDUCERS = {"min", "max", "mean", "sum", "last", "integral", "duration", "longest", "transitions"}
BOOLEAN_REDUCERS = {"duration", "longest", "transitions"}
MAX_SKILLS = 16
MAX_METRICS = 12
MAX_GUARDS = 6
MAX_CASES = 5
MAX_EXPRESSION = 600
MAX_TITLE = 100
MAX_ID = 40
MAX_PROGRAM = 40
MAX_CASE_ID = 40
MAX_DISTURBANCES = 8


class ContractError(ValueError):
    """A skill contract or its measured evidence is not acceptable."""


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _text(value, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError(f"{name} must be nonempty text, at most {limit} characters")
    return value


def _number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value):
        raise ContractError(f"{name} must be a finite number in {low}..{high}")
    return value


def _keys(value, allowed, name="request"):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ContractError(f"{name} accepts only these fields: {', '.join(allowed)}")


def _expression(value, name):
    """Check that a contract expression is a bounded, well-formed expression.

    The expression is parsed, not evaluated: the names it refers to (`s`,
    `prev`, `initial`, `r`) only exist at measurement time.
    """
    _text(value, MAX_EXPRESSION, name)
    try:
        parse(value)
    except ValueError as exc:
        raise ContractError(f"{name} expression: " + str(exc)[:180]) from exc
    return value


def validate_contract(contract: dict) -> dict:
    """Validate one contract and return a normalized copy with a version."""
    if not isinstance(contract, dict):
        raise ContractError("a skill contract must be an object")
    _keys(contract, (
        "id", "title", "depends", "program", "metrics", "score", "success",
        "guards", "cases", "min_delta", "attempt_limit", "plateau_limit",
    ), "skill contract")
    result = copy.deepcopy(contract)
    skill_id = _text(result.get("id"), MAX_ID, "skill id")
    _text(result.get("title"), MAX_TITLE, "skill title")
    _text(result.get("program"), MAX_PROGRAM, "program")
    depends = result.setdefault("depends", [])
    if not isinstance(depends, list) or len(depends) > 12 or any(not isinstance(item, str) for item in depends):
        raise ContractError("depends must be a list of unique skill ids")
    if len(set(depends)) != len(depends):
        raise ContractError("depends must be a list of unique skill ids")
    metrics = result.get("metrics")
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= MAX_METRICS:
        raise ContractError(f"skill needs 1..{MAX_METRICS} metrics")
    names = set()
    for metric in metrics:
        _keys(metric, ("name", "expression", "reduce", "target", "label", "unit"), "metric")
        name = _text(metric.get("name"), MAX_ID, "metric name")
        if name in names:
            raise ContractError("duplicate metric name")
        names.add(name)
        _expression(metric.get("expression"), "metric")
        if metric.get("reduce") not in REDUCERS:
            raise ContractError("unknown metric reducer")
        if "target" in metric:
            _keys(metric["target"], ("min", "max"), "metric target")
            if not metric["target"]:
                raise ContractError("metric target is empty")
            for value in metric["target"].values():
                _number(value, -1e8, 1e8, "metric target")
            if metric["target"].get("min", -1e8) > metric["target"].get("max", 1e8):
                raise ContractError("metric target min>max")
    _expression(result.get("score"), "fitness score")
    _expression(result.get("success"), "success predicate")
    guards = result.setdefault("guards", [])
    if not isinstance(guards, list) or len(guards) > MAX_GUARDS:
        raise ContractError(f"up to {MAX_GUARDS} guards")
    for guard in guards:
        _expression(guard, "guard")
    cases = result.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ContractError(f"skill needs 1..{MAX_CASES} cases")
    case_ids = set()
    for case in cases:
        _keys(case, ("id", "frames", "start", "split", "velocity", "impulses", "events"), "case")
        name = _text(case.get("id"), MAX_CASE_ID, "case id")
        if name in case_ids:
            raise ContractError("duplicate case id")
        case_ids.add(name)
        if type(case.get("frames")) is not int or not 30 <= case["frames"] <= 1200:
            raise ContractError("case frames 30..1200")
        if case.get("start") not in ("neutral", "captured") or case.get("split") not in ("train", "validation"):
            raise ContractError("case start/split must be explicit")
        for field in ("impulses", "events"):
            values = case.get(field, [])
            if not isinstance(values, list) or len(values) > MAX_DISTURBANCES:
                raise ContractError(f"up to {MAX_DISTURBANCES} disturbances/events")
            for value in values:
                _keys(value, ("at", "joint", "value") if field == "impulses" else ("at", "id"), field)
                if type(value.get("at")) is not int or not 0 <= value["at"] < case["frames"]:
                    raise ContractError("disturbance at must be a case frame index")
                if field == "impulses":
                    _text(value.get("joint"), MAX_ID, "impulse joint")
                    impulse = value.get("value")
                    if not isinstance(impulse, list) or len(impulse) != 2:
                        raise ContractError("impulse value must be [x,y]")
                    for component in impulse:
                        _number(component, -2000, 2000, "impulse value")
                else:
                    _text(value.get("id"), 60, "test event")
    if not any(case["split"] == "validation" for case in cases):
        raise ContractError("include at least one explicit validation case")
    for key, default, low, high in (("min_delta", 0.001, 0, 100000), ("attempt_limit", 12, 1, 20), ("plateau_limit", 5, 2, 10)):
        result.setdefault(key, default)
        _number(result[key], low, high, key)
        if key != "min_delta" and type(result[key]) is not int:
            raise ContractError(key + " must be integer")
    result["version"] = digest(result)[:16]
    return result


def plan_contracts(plan: dict) -> dict:
    """Validate a decomposition of skill contracts and return the plan."""
    if not isinstance(plan, dict):
        raise ContractError("a plan must be an object")
    _keys(plan, ("goal", "target", "skills", "reason"), "plan")
    _text(plan.get("goal"), 400, "goal")
    _text(plan.get("reason"), 400, "decomposition reason")
    supplied = plan.get("skills")
    if not isinstance(supplied, list) or not 1 <= len(supplied) <= MAX_SKILLS:
        raise ContractError(f"plan needs 1..{MAX_SKILLS} skill contracts")
    contracts: dict[str, dict] = {}
    for raw in supplied:
        contract = validate_contract(raw)
        if contract["id"] in contracts:
            raise ContractError("duplicate skill id")
        contracts[contract["id"]] = contract
    target = plan.get("target")
    if not isinstance(target, str) or target not in contracts:
        raise ContractError("target skill must exist")
    visited: set[str] = set()

    def visit(skill_id, stack):
        if skill_id in stack:
            raise ContractError("skill dependencies contain a cycle")
        if skill_id not in contracts:
            raise ContractError("unknown prerequisite: " + str(skill_id))
        if skill_id in visited:
            return
        for dependency in contracts[skill_id]["depends"]:
            visit(dependency, stack | {skill_id})
        visited.add(skill_id)

    for skill_id in contracts:
        visit(skill_id, set())
    return {"goal": plan["goal"], "reason": plan["reason"], "target": target, "skills": contracts}


def grade_report(contract: dict, report: dict) -> dict:
    """Grade a host-measured report against a contract.

    The report must come from a trusted host measurement. A model-supplied
    success claim is never accepted here.
    """
    try:
        if report.get("passed") is not True:
            raise ValueError(report.get("error", "execution report failed"))
        score = evaluate(contract["score"], {"r": report})
        success = evaluate(contract["success"], {"r": report})
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError("fitness score must be finite numeric")
        if type(success) is not bool:
            raise ValueError("success must be boolean")
        guards = [evaluate(guard, {"r": report}) for guard in contract["guards"]]
        if any(type(guard) is not bool for guard in guards):
            raise ValueError("guards must be boolean")
        checks = []
        for metric in contract["metrics"]:
            target = metric.get("target", {})
            value = report["metrics"][metric["name"]]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("measured metric must be finite numeric")
            checks.append({
                "metric": metric["name"],
                "value": value,
                "target": target,
                "passed": target.get("min", -1e100) <= value <= target.get("max", 1e100),
            })
        return {
            "score": score,
            "passed": success and all(guards) and all(check["passed"] for check in checks),
            "guards_pass": all(guards),
            "success": success,
            "metrics": checks,
            "guards": [{"expression": guard, "passed": value} for guard, value in zip(contract["guards"], guards)],
            "report": {key: value for key, value in report.items() if key not in ("objects", "ropes")},
        }
    except (ValueError, KeyError) as exc:
        return {
            "score": None, "passed": False, "guards_pass": False,
            "error": str(exc)[:200], "metrics": report.get("metrics", {}),
        }


def skill_statuses(contracts: dict, attempts: dict, bindings: dict) -> dict:
    """Report the status of every skill: mastered, blocked or ready."""
    result: dict[str, dict] = {}

    def check(skill_id):
        if skill_id in result:
            return result[skill_id]
        contract = contracts[skill_id]
        dependencies = {dependency: check(dependency) for dependency in contract["depends"]}
        binding = bindings.get(skill_id)
        rows = [
            attempt for attempt in attempts.get(skill_id, [])
            if attempt.get("contract") == contract["version"]
        ]
        valid = next(
            (
                attempt for attempt in reversed(rows)
                if attempt.get("binding") == binding and attempt.get("applied")
            ),
            None,
        )
        mastered = bool(
            valid and valid.get("passed")
            and all(dependency["status"] == "mastered" for dependency in dependencies.values())
        )
        blocked = [
            dependency for dependency, state in dependencies.items()
            if state["status"] != "mastered"
        ]
        recent = rows[-contract["plateau_limit"]:]
        plateau = len(recent) >= contract["plateau_limit"] and not any(
            attempt.get("improved") for attempt in recent
        )
        budget = len(rows) >= contract["attempt_limit"]
        if mastered:
            status = "mastered"
        elif blocked or budget or plateau:
            status = "blocked"
        else:
            status = "ready"
        result[skill_id] = {
            "id": skill_id,
            "title": contract["title"],
            "status": status,
            "depends": contract["depends"],
            "attempts": len(rows),
            "limit": contract["attempt_limit"],
            "contract": contract["version"],
            "score": valid.get("score") if valid else None,
            "reason": (
                "prerequisites: " + ", ".join(blocked) if blocked
                else "attempt budget exhausted" if budget and not mastered
                else "fitness plateau; change hypothesis or revise the plan explicitly" if plateau and not mastered
                else None
            ),
            "last": (
                {key: rows[-1].get(key) for key in ("id", "score", "passed", "improved", "applied", "bottleneck")}
                if rows else None
            ),
        }
        return result[skill_id]

    for skill_id in contracts:
        check(skill_id)
    return result


def progress(before: dict, after: dict, min_delta: float):
    """Decide whether a candidate may be published, and whether it improved."""
    improved = after["score"] is not None and (
        before["score"] is None or after["score"] > before["score"] + min_delta
    )
    previous = {case["id"]: case for case in before.get("cases", [])}
    validation_ok = all(
        case["score"] is not None
        and (
            previous.get(case["id"], {}).get("score") is None
            or case["score"] >= previous[case["id"]]["score"] - min_delta
        )
        for case in after.get("cases", [])
        if case["split"] == "validation"
    )
    accepted = (
        after["guards_pass"]
        and (after["passed"] or (improved and validation_ok))
        and not (before["passed"] and not after["passed"])
    )
    return accepted, improved
