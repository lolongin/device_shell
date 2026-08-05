"""In-memory result store with deterministic output summarization."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

MAX_ENTRIES = 500
TTL_SECONDS = 24 * 3600
_MAX_IMPORTANT_LINES = 5
_TAIL_LINES = 20
# Error markers: "Error:", "%.../4/..." severity-4+ syslog lines.
_ERROR_PATTERNS = (
    re.compile(r"\bError\b", re.IGNORECASE),
    re.compile(r"\bFailed\b", re.IGNORECASE),
    re.compile(r"^%\S+%%[A-Z0-9]+/([4-9])/", re.MULTILINE),
)


@dataclass(slots=True)
class StoredResult:
    result_id: str
    kind: str
    status: str
    output: str
    summary: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_monotonic: float = 0.0


def summarize_output(
    output: str,
    *,
    max_important_lines: int = _MAX_IMPORTANT_LINES,
    tail_lines: int = _TAIL_LINES,
) -> tuple[int, list[str]]:
    lines = output.splitlines()
    hits = []
    for index, line in enumerate(lines):
        if any(pattern.search(line) for pattern in _ERROR_PATTERNS):
            hits.append((index, line.strip()))
    if hits:
        return len(hits), [line for _, line in hits[:max_important_lines]]
    tail = lines[-tail_lines:] if tail_lines else lines
    return 0, [line.strip() for line in tail]


class ResultStore:
    def __init__(
        self,
        *,
        max_entries: int = MAX_ENTRIES,
        ttl_seconds: int = TTL_SECONDS,
        clock: Any = time.monotonic,
    ) -> None:
        self.max_entries = max(50, min(5000, int(max_entries)))
        self.ttl_seconds = max(1, min(168, int(ttl_seconds))) * 3600
        self.clock = clock
        self._entries: dict[str, StoredResult] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    def store(
        self,
        kind: str,
        output: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        with self._lock:
            self._prune_expired_locked()
            result_id = "R" + uuid4().hex[:8]
            meta = dict(metadata or {})
            # The stored summary is computed here from the real status/exit_code/
            # duration passed via metadata, plus the deterministic error scan of
            # the output. This keeps `ai_get_result` returning the SAME summary
            # the caller returned — no placeholder, no separate finalize step.
            status = str(meta.get("status") or "success")
            exit_code = int(meta.get("exit_code") or 0)
            command_count = int(meta.get("command_count", 1))
            duration_ms = int(meta.get("duration_ms", 0))
            error_count, important_lines = summarize_output(output)
            summary = {
                "status": status,
                "exit_code": exit_code,
                "command_count": command_count,
                "error_count": error_count,
                "important_lines": important_lines,
                "duration_ms": duration_ms,
            }
            entry = StoredResult(
                result_id=result_id,
                kind=kind,
                status=status,
                output=output,
                summary=summary,
                metadata=meta,
                created_monotonic=self.clock(),
            )
            self._entries[result_id] = entry
            self._order.append(result_id)
            while len(self._order) > self.max_entries:
                oldest = self._order.pop(0)
                self._entries.pop(oldest, None)
            return result_id

    def get(self, result_id: str) -> StoredResult | None:
        with self._lock:
            entry = self._entries.get(result_id)
            if entry is None:
                return None
            if self.clock() - entry.created_monotonic > self.ttl_seconds:
                self._entries.pop(result_id, None)
                self._order = [rid for rid in self._order if rid != result_id]
                return None
            if self._order:
                self._order.remove(result_id)
                self._order.append(result_id)
            return entry

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._prune_expired_locked()
            return {
                "count": len(self._entries),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
            }

    def _prune_expired_locked(self) -> None:
        now = self.clock()
        expired = [
            rid for rid in self._order
            if now - self._entries[rid].created_monotonic > self.ttl_seconds
        ]
        for rid in expired:
            self._entries.pop(rid, None)
            self._order.remove(rid)
