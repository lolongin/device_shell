"""Bounded matching for incremental terminal output."""

from __future__ import annotations

import re


MAX_MATCH_BUFFER = 64 * 1024


class TerminalMatcher:
    def __init__(self, mode: str, pattern: str, *, case_sensitive: bool = False) -> None:
        normalized_mode = str(mode or "contains").strip().lower()
        if normalized_mode not in {"contains", "regex"}:
            raise ValueError(f"unsupported match mode: {normalized_mode}")
        if not str(pattern):
            raise ValueError("match pattern is required")
        self.mode = normalized_mode
        self.pattern = str(pattern)
        self.case_sensitive = bool(case_sensitive)
        self._buffer = ""
        self._flags = 0 if self.case_sensitive else re.IGNORECASE
        self._compiled = re.compile(self.pattern, self._flags) if self.mode == "regex" else None

    def feed(self, text: str) -> bool:
        self._buffer = (self._buffer + str(text))[-MAX_MATCH_BUFFER:]
        if self.mode == "regex":
            return bool(self._compiled and self._compiled.search(self._buffer))
        haystack = self._buffer if self.case_sensitive else self._buffer.casefold()
        needle = self.pattern if self.case_sensitive else self.pattern.casefold()
        return needle in haystack

    @property
    def buffer(self) -> str:
        return self._buffer
