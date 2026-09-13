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
    if operator == "是否为空":
        return left is None or str(left).strip() == ""
    if left is None:
        return False
    left_text, right_text = str(left), str(right)
    if operator == "等于":
        return left == right or left_text.casefold() == right_text.casefold()
    if operator == "不等于":
        return not (left == right or left_text.casefold() == right_text.casefold())
    if operator == "包含":
        return right_text.casefold() in left_text.casefold()
    if operator == "不包含":
        return right_text.casefold() not in left_text.casefold()
    if operator in {"大于", "小于"}:
        try:
            left_value, right_value = Decimal(left_text), Decimal(right_text)
        except InvalidOperation:
            left_value, right_value = left_text.casefold(), right_text.casefold()
        return left_value > right_value if operator == "大于" else left_value < right_value
    return False


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
