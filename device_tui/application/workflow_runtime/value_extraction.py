"""Generic text extraction for workflow variable assignments."""

from __future__ import annotations

import re
from typing import Any, Mapping


def extract_value(source: Any, extract: Mapping[str, Any]) -> tuple[str, bool]:
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
        return text[line_start:line_end].rstrip("\r"), True

    try:
        return str(match.group(group)), True
    except (IndexError, re.error) as exc:
        raise ValueError(f"invalid extraction group: {group}") from exc


__all__ = ["extract_value"]
