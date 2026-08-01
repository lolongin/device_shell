"""Redacted JSONL audit persistence."""

from __future__ import annotations

import json
from pathlib import Path
import re
import threading
from typing import Any

SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(password|passwd|secret|token)\s*[=:]\s*(\S+)"),
    re.compile(r"(?i)(://[^:/\s]+:)([^@\s]+)(@)"),
)

def redact_text(text: str) -> str:
    redacted = text
    redacted = SENSITIVE_PATTERNS[0].sub(r"\1=***", redacted)
    redacted = SENSITIVE_PATTERNS[1].sub(r"\1***\3", redacted)
    return redacted

class AuditLogger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, entry: dict[str, Any]) -> None:
        if self.path is None:
            return
        payload = self._redact_value(entry)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "***" if key.casefold() in {"token", "approval_token", "password"} else self._redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, str):
            return redact_text(value)
        return value
