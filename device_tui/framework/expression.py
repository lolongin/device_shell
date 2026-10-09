"""Restricted expression parsing shared by workflow compilation and runtime."""

from __future__ import annotations

import ast
import operator
import re
from typing import Any, Mapping


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}
_MAX_EXPRESSION_LENGTH = 4096
_MAX_AST_NODES = 200
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*)\}")


def _bind_references(expression: str, values: Mapping[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    bound = dict(values or {})

    def replace(match: re.Match[str]) -> str:
        name = f"bindingref{len(bound)}"
        if values is not None:
            current: Any = values
            for segment in match.group(1).split("."):
                if isinstance(current, Mapping):
                    current = current[segment]
                elif isinstance(current, (list, tuple)) and segment.isdigit():
                    current = current[int(segment)]
                else:
                    raise ValueError(f"unresolved expression reference: {match.group(0)}")
            bound[name] = current
        return name

    return _REFERENCE.sub(replace, expression), bound


def validate_expression(expression: str) -> None:
    source, _ = _bind_references(str(expression).strip())
    if not source or len(source) > _MAX_EXPRESSION_LENGTH:
        raise ValueError("unsupported expression syntax")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ValueError("unsupported expression syntax") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
        raise ValueError("unsupported expression complexity")
    _validate(tree.body)


def evaluate_expression(expression: str, values: Mapping[str, Any]) -> Any:
    try:
        source, bound = _bind_references(str(expression).strip(), values)
        validate_expression(source)
        tree = ast.parse(source, mode="eval")
        return _evaluate(tree.body, bound)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError, re.error) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("unsupported expression"):
            raise
        raise ValueError(f"unsupported expression: {expression}") from exc


def _validate(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool, type(None))):
            return
    elif isinstance(node, ast.Name):
        if not node.id.startswith("_"):
            return
    elif isinstance(node, ast.Attribute):
        if not node.attr.startswith("_"):
            _validate(node.value)
            return
    elif isinstance(node, ast.Subscript):
        _validate(node.value)
        _validate(node.slice)
        return
    elif isinstance(node, (ast.List, ast.Tuple)):
        for item in node.elts:
            _validate(item)
        return
    elif isinstance(node, ast.Dict):
        if all(key is not None for key in node.keys):
            for key, value in zip(node.keys, node.values):
                _validate(key)
                _validate(value)
            return
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "regex_match" and len(node.args) == 2 and not node.keywords:
        for arg in node.args:
            _validate(arg)
        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            try:
                re.compile(node.args[0].value)
            except re.error as exc:
                raise ValueError("unsupported expression regex") from exc
        return
    elif isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        for item in node.values:
            _validate(item)
        return
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
        _validate(node.operand)
        return
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        _validate(node.left)
        _validate(node.right)
        return
    elif isinstance(node, ast.Compare) and all(type(op) in _CMPOPS for op in node.ops):
        _validate(node.left)
        for comparator in node.comparators:
            _validate(comparator)
        return
    raise ValueError("unsupported expression syntax")


def _evaluate(node: ast.AST, values: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in values:
            return values[node.id]
        raise KeyError(node.id)
    if isinstance(node, ast.Attribute):
        owner = _evaluate(node.value, values)
        if not isinstance(owner, Mapping) or node.attr not in owner:
            raise ValueError("unsupported expression attribute")
        return owner[node.attr]
    if isinstance(node, ast.Subscript):
        owner = _evaluate(node.value, values)
        key = _evaluate(node.slice, values)
        return owner[key]
    if isinstance(node, ast.List):
        return [_evaluate(item, values) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_evaluate(item, values) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {_evaluate(key, values): _evaluate(value, values) for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "regex_match":
        return re.search(str(_evaluate(node.args[0], values)), str(_evaluate(node.args[1], values))) is not None
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for item in node.values:
                result = _evaluate(item, values)
                if not result:
                    return result
            return result
        result = False
        for item in node.values:
            result = _evaluate(item, values)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, values)
        return not value if isinstance(node.op, ast.Not) else (-value if isinstance(node.op, ast.USub) else +value)
    if isinstance(node, ast.BinOp):
        return _BINOPS[type(node.op)](_evaluate(node.left, values), _evaluate(node.right, values))
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, values)
        for op, comparator in zip(node.ops, node.comparators):
            right = _evaluate(comparator, values)
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True
    raise ValueError("unsupported expression syntax")


__all__ = ["evaluate_expression", "validate_expression"]
