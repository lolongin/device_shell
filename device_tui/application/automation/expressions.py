"""Safe expressions and templates for terminal automation."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable, Mapping
from typing import Any

from device_tui.application.errors import UnsupportedOperationError


_TEMPLATE_EXPRESSION = re.compile(r"\{\{\s*(?!secret:)(.+?)\s*}}")
_FULL_TEMPLATE_EXPRESSION = re.compile(r"^\s*\{\{\s*(?!secret:)(.+?)\s*}}\s*$")
_MAX_EXPRESSION_LENGTH = 4_000
_MAX_RENDERED_LENGTH = 200_000


def _lower(value: object) -> str:
    return str(value).lower()


def _upper(value: object) -> str:
    return str(value).upper()


def _replace(value: object, old: object, new: object) -> str:
    return str(value).replace(str(old), str(new))


def _join(separator: object, values: object) -> str:
    if not isinstance(values, (list, tuple)):
        raise UnsupportedOperationError("join 的第二个参数必须是列表。")
    return str(separator).join(str(value) for value in values)


_FUNCTIONS: dict[str, Callable[..., object]] = {
    "abs": abs,
    "bool": bool,
    "float": float,
    "int": int,
    "join": _join,
    "len": len,
    "lower": _lower,
    "max": max,
    "min": min,
    "replace": _replace,
    "round": round,
    "str": str,
    "upper": _upper,
}

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[object, object], object]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_COMPARISON_OPERATORS: dict[type[ast.cmpop], Callable[[object, object], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


class SafeAutomationExpression:
    """Evaluate a small, side-effect-free expression language."""

    @classmethod
    def evaluate(cls, expression: str, context: Mapping[str, object]) -> object:
        source = expression.strip()
        if not source:
            raise UnsupportedOperationError("自动化表达式不能为空。")
        if len(source) > _MAX_EXPRESSION_LENGTH:
            raise UnsupportedOperationError("自动化表达式过长。")
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as error:
            raise UnsupportedOperationError(f"自动化表达式无效：{error.msg}") from error
        try:
            value = cls._evaluate_node(tree.body, context)
        except UnsupportedOperationError:
            raise
        except (ArithmeticError, TypeError, ValueError, KeyError, IndexError) as error:
            raise UnsupportedOperationError(f"自动化表达式计算失败：{error}") from error
        if len(str(value)) > _MAX_RENDERED_LENGTH:
            raise UnsupportedOperationError("自动化表达式结果过长。")
        return value

    @classmethod
    def _evaluate_node(cls, node: ast.AST, context: Mapping[str, object]) -> object:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, float, bool, type(None))):
                return node.value
        if isinstance(node, ast.Name):
            if node.id in context:
                return context[node.id]
            raise UnsupportedOperationError(f"自动化变量尚未赋值：{node.id}")
        if isinstance(node, ast.Attribute):
            value = cls._evaluate_node(node.value, context)
            if isinstance(value, Mapping) and node.attr in value:
                return value[node.attr]
            raise UnsupportedOperationError(f"自动化属性不存在：{node.attr}")
        if isinstance(node, ast.Subscript):
            value = cls._evaluate_node(node.value, context)
            key = cls._evaluate_node(node.slice, context)
            return value[key]  # type: ignore[index]
        if isinstance(node, ast.List):
            return [cls._evaluate_node(item, context) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(cls._evaluate_node(item, context) for item in node.elts)
        if isinstance(node, ast.Dict):
            return {
                cls._evaluate_node(key, context): cls._evaluate_node(value, context)
                for key, value in zip(node.keys, node.values)
                if key is not None
            }
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = cls._evaluate_node(node.left, context)
            right = cls._evaluate_node(node.right, context)
            if isinstance(node.op, ast.Pow) and abs(float(right)) > 10:
                raise UnsupportedOperationError("表达式指数不能超过 10。")
            if isinstance(node.op, ast.Mult):
                repeat = right if isinstance(right, int) else left if isinstance(left, int) else 0
                if abs(repeat) > 10_000:
                    raise UnsupportedOperationError("表达式重复次数过大。")
            return _BINARY_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            value = cls._evaluate_node(node.operand, context)
            if isinstance(node.op, ast.Not):
                return not value
            if isinstance(node.op, ast.USub):
                return -value  # type: ignore[operator]
            if isinstance(node.op, ast.UAdd):
                return +value  # type: ignore[operator]
        if isinstance(node, ast.BoolOp):
            values = node.values
            if isinstance(node.op, ast.And):
                result: object = True
                for value_node in values:
                    result = cls._evaluate_node(value_node, context)
                    if not result:
                        return result
                return result
            result = False
            for value_node in values:
                result = cls._evaluate_node(value_node, context)
                if result:
                    return result
            return result
        if isinstance(node, ast.Compare):
            left = cls._evaluate_node(node.left, context)
            for operation, comparator in zip(node.ops, node.comparators):
                right = cls._evaluate_node(comparator, context)
                function = _COMPARISON_OPERATORS.get(type(operation))
                if function is None or not function(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            branch = node.body if cls._evaluate_node(node.test, context) else node.orelse
            return cls._evaluate_node(branch, context)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = _FUNCTIONS.get(node.func.id)
            if function is None:
                raise UnsupportedOperationError(f"表达式函数不受支持：{node.func.id}")
            if node.keywords:
                raise UnsupportedOperationError("表达式函数不支持命名参数。")
            return function(*(cls._evaluate_node(argument, context) for argument in node.args))
        raise UnsupportedOperationError(
            f"自动化表达式包含不支持的语法：{type(node).__name__}"
        )

    @classmethod
    def render(cls, template: str, context: Mapping[str, object]) -> str:
        def replace_expression(match: re.Match[str]) -> str:
            return cls.format_value(cls.evaluate(match.group(1), context))

        rendered = _TEMPLATE_EXPRESSION.sub(replace_expression, template)
        if len(rendered) > _MAX_RENDERED_LENGTH:
            raise UnsupportedOperationError("自动化模板结果过长。")
        return rendered

    @classmethod
    def value(cls, template: str, context: Mapping[str, object]) -> object:
        match = _FULL_TEMPLATE_EXPRESSION.fullmatch(template)
        if match:
            return cls.evaluate(match.group(1), context)
        return cls.render(template, context)

    @staticmethod
    def format_value(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return ""
        return str(value)


def template_expression_pattern() -> re.Pattern[str]:
    """Expose the template matcher for validation without duplicating syntax."""

    return _TEMPLATE_EXPRESSION
