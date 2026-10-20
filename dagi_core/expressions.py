"""Bounded expression evaluation for agent-authored contracts and policies.

The evaluator walks a small allow-listed AST. It never calls eval/exec, never
imports modules, never reaches attributes of host objects, and bounds work,
numbers and result size. It is the shared language behind skill fitness
contracts, goal checks and agent policies.
"""
from __future__ import annotations

import ast
import json
import math
import operator

FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "atan2": math.atan2,
    "sqrt": math.sqrt, "floor": math.floor, "abs": abs,
    "min": min, "max": max, "round": round, "len": len, "hypot": math.hypot,
    "clamp": lambda x, lo, hi: max(lo, min(hi, x)),
    "get": lambda obj, key, default=0: obj.get(key, default),
}
BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
COMPARE = {
    ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
    ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne,
}
MAX_SOURCE = 8000
MAX_NODES = 600
MAX_OPERATIONS = 1200
MAX_VALUE_LENGTH = 128
MAX_RESULT_LENGTH = 8000
MAX_NUMBER = 1e9
MAX_EXPONENT = 6


def parse(source: str):
    """Parse a bounded expression and return its AST body."""
    if not isinstance(source, str) or not 1 <= len(source) <= MAX_SOURCE:
        raise ValueError(f"expression must be text, 1..{MAX_SOURCE} characters")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("invalid expression: " + str(exc)[:180]) from exc
    nodes = list(ast.walk(tree))
    allowed = (
        ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Subscript,
        ast.Dict, ast.List, ast.Tuple, ast.BinOp, ast.UnaryOp, ast.BoolOp,
        ast.Compare, ast.IfExp, ast.Call, ast.USub, ast.UAdd, ast.Not,
        ast.And, ast.Or, *BINARY, *COMPARE,
    )
    if len(nodes) > MAX_NODES or any(not isinstance(node, allowed) for node in nodes):
        raise ValueError(
            "expression supports bounded expressions, dictionaries, indexing, math and conditions; "
            "no attributes, loops or imports"
        )
    if any(
        isinstance(node, ast.Call)
        and (not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords)
        for node in nodes
    ):
        raise ValueError("expression calls only: " + ", ".join(sorted(FUNCTIONS)))
    return tree.body


def evaluate(source: str, context: dict):
    """Evaluate a bounded expression against a context of names."""
    budget = [MAX_OPERATIONS]

    def check(value):
        if isinstance(value, (int, float)) and (not math.isfinite(value) or abs(value) > MAX_NUMBER):
            raise ValueError("expression number out of bounds")
        if isinstance(value, (str, list, tuple, dict)) and len(value) > MAX_VALUE_LENGTH:
            raise ValueError("expression value too large")
        return value

    def visit(node):
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("expression operation budget exceeded")
        if isinstance(node, ast.Constant):
            return check(node.value)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            if node.id not in context:
                raise ValueError("unknown expression variable: " + node.id)
            return context[node.id]
        if isinstance(node, ast.Subscript):
            return visit(node.value)[visit(node.slice)]
        if isinstance(node, (ast.List, ast.Tuple)):
            return check([visit(item) for item in node.elts])
        if isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise ValueError("dictionary unpacking is not supported")
            return check({visit(key): visit(value) for key, value in zip(node.keys, node.values)})
        if isinstance(node, ast.IfExp):
            return visit(node.body if visit(node.test) else node.orelse)
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            return check(
                not value if isinstance(node.op, ast.Not)
                else -value if isinstance(node.op, ast.USub)
                else +value
            )
        if isinstance(node, ast.BoolOp):
            value = None
            for item in node.values:
                value = visit(item)
                if isinstance(node.op, ast.And) and not value or isinstance(node.op, ast.Or) and value:
                    break
            return value
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
                raise ValueError("expression arithmetic requires numbers")
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise ValueError(f"expression exponent limit: {MAX_EXPONENT}")
            return check(BINARY[type(node.op)](left, right))
        if isinstance(node, ast.Compare):
            left = visit(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = visit(comparator)
                if not COMPARE[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            return check(FUNCTIONS[node.func.id](*(visit(item) for item in node.args)))
        raise ValueError("unsupported expression")

    try:
        result = visit(parse(source))
        if len(json.dumps(result, allow_nan=False)) > MAX_RESULT_LENGTH:
            raise ValueError("expression result too large")
        return result
    except (TypeError, KeyError, IndexError, ArithmeticError, RecursionError) as exc:
        raise ValueError("expression runtime: " + str(exc)[:180]) from exc
