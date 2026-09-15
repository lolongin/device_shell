"""Small, serializable predicates used by conditional TaskPlan nodes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def _value(values: Mapping[str, Any], field: str) -> Any:
    """Resolve a dotted field, then search nested activity output objects."""
    parts = [part for part in str(field).split(".") if part]
    if not parts:
        return None

    def direct(current: Any) -> Any:
        if not isinstance(current, Mapping):
            return None
        candidate = current
        for part in parts:
            if not isinstance(candidate, Mapping) or part not in candidate:
                break
            candidate = candidate[part]
        else:
            return candidate
        for child in current.values():
            if isinstance(child, Mapping):
                found = direct(child)
                if found is not None:
                    return found
        return None

    return direct(values)


def _compare(left: Any, right: Any, operator: str) -> bool:
    normalized = _normalize_operator(operator)
    if normalized == "empty":
        return left is None or str(left).strip() == ""
    if left is None:
        return False
    left_text, right_text = str(left), str(right)
    if normalized == "equals":
        return left == right or left_text.casefold() == right_text.casefold()
    if normalized == "not_equals":
        return not (left == right or left_text.casefold() == right_text.casefold())
    if normalized == "contains":
        return right_text.casefold() in left_text.casefold()
    if normalized == "not_contains":
        return right_text.casefold() not in left_text.casefold()
    if normalized in {"greater_than", "less_than"}:
        try:
            left_value, right_value = Decimal(left_text), Decimal(right_text)
        except InvalidOperation:
            left_value, right_value = left_text.casefold(), right_text.casefold()
        return left_value > right_value if normalized == "greater_than" else left_value < right_value
    return False


def _normalize_operator(operator: str) -> str:
    key = str(operator).strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "等于": "equals",
        "==": "equals",
        "=": "equals",
        "eq": "equals",
        "equals": "equals",
        "不等于": "not_equals",
        "!=": "not_equals",
        "<>": "not_equals",
        "ne": "not_equals",
        "not_equals": "not_equals",
        "包含": "contains",
        "contains": "contains",
        "includes": "contains",
        "不包含": "not_contains",
        "not_contains": "not_contains",
        "大于": "greater_than",
        ">": "greater_than",
        "gt": "greater_than",
        "greater_than": "greater_than",
        "小于": "less_than",
        "<": "less_than",
        "lt": "less_than",
        "less_than": "less_than",
        "是否为空": "empty",
        "empty": "empty",
        "is_empty": "empty",
    }
    return aliases.get(key, key)


def evaluate_rules(
    rules: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    values: Mapping[str, Any],
    *,
    logical_operator: str = "AND",
) -> bool:
    """Evaluate business-language rules without executing arbitrary expressions."""
    results = [
        _compare(_value(values, str(rule.get("field", ""))), rule.get("value", ""), str(rule.get("operator", "")))
        for rule in rules
        if isinstance(rule, Mapping) and str(rule.get("field", "")).strip()
    ]
    if not results:
        return False
    return any(results) if str(logical_operator).upper() == "OR" else all(results)


__all__ = ["evaluate_rules"]
