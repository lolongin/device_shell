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
    def __init__(
        self,
        path: Path | None = None,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
    ) -> None:
        self.path = path
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self.backup_count = max(1, int(backup_count))
        self._lock = threading.Lock()

    def write(self, entry: dict[str, Any]) -> None:
        if self.path is None:
            return
        payload = self._redact_value(entry)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(len((line + "\n").encode("utf-8")))
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            current_size = self.path.stat().st_size
        except OSError:
            return
        if current_size + incoming_bytes <= self.max_bytes:
            return
        for index in range(self.backup_count, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            target = self.path.with_name(f"{self.path.name}.{index + 1}")
            if index == self.backup_count:
                source.unlink(missing_ok=True)
            elif source.exists():
                source.replace(target)
        self.path.replace(self.path.with_name(f"{self.path.name}.1"))

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
