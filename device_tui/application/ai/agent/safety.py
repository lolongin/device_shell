"""Sanitize Agent messages before model, event, or UI delivery."""

from __future__ import annotations

import re
from typing import Any

from device_tui.infrastructure.audit import redact_text

_SECRET_KEY = re.compile(r"(?i)(password|passwd|secret(?!_ref)|token|api[_-]?key|authorization|cookie|private[_-]?key)")
_SECRET_TEXT = re.compile(r'''(?ix)(["']?(?:password|passwd|secret|token|api[_-]?key|authorization|cookie)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''')


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): "***" if _SECRET_KEY.search(str(key)) else sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TEXT.sub(r"\1***", redact_text(value))[:100_000]
    return value
