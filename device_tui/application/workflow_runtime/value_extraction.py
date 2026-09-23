"""Generic text extraction for workflow variable assignments."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


def extract_value(source: Any, extract: Mapping[str, Any]) -> tuple[Any, bool]:
    """Return the first configured match and whether one was found."""
    pattern = str(extract.get("pattern") or "")
    if not pattern:
        raise ValueError("invalid extraction pattern: pattern is required")

    mode = str(extract.get("mode") or "match").strip().lower()
    if mode not in {"match", "line"}:
        raise ValueError("invalid extraction mode: expected match or line")

    raw_group = extract.get("group", 0)
    if isinstance(raw_group, bool):
        raise ValueError("invalid extraction group: expected a non-negative integer")
    try:
        group = int(raw_group)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid extraction group: expected a non-negative integer") from exc
    if group < 0:
        raise ValueError("invalid extraction group: expected a non-negative integer")

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid extraction pattern: {exc}") from exc

    text = "" if source is None else str(source)
    match = compiled.search(text)
    if match is None:
        return "", False

    if mode == "line":
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)
        value = text[line_start:line_end].rstrip("\r")
    else:
        try:
            value = str(match.group(group))
        except (IndexError, re.error) as exc:
            raise ValueError(f"invalid extraction group: {group}") from exc

    if bool(extract.get("trim", False)):
        value = value.strip()
    return convert_value(value, extract.get("convert", "string")), True


def convert_value(value: Any, conversion: Any) -> Any:
    """Convert an extracted value with deterministic, user-facing failures."""
    target = str(conversion or "string").strip().lower()
    if target == "string":
        return "" if value is None else str(value)
    text = "" if value is None else str(value).strip()
    try:
        if target == "integer":
            if not re.fullmatch(r"[+-]?\d+", text):
                raise ValueError
            return int(text)
        if target == "number":
            return float(text)
        if target == "boolean":
            normalized = text.casefold()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
            raise ValueError
        if target == "json":
            return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot convert extracted value to {target}") from exc
    raise ValueError(f"invalid extraction conversion: {target}")


__all__ = ["convert_value", "extract_value"]
