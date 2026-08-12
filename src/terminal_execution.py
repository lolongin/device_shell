"""Helpers for command-specific terminal output and prompt detection."""

from __future__ import annotations

import re


ANSI_ESCAPE_RE = re.compile(
    r"(?:\x1B[@-_][0-?]*[ -/]*[@-~])|(?:\x9B[0-?]*[ -/]*[@-~])"
)
PROMPT_PATTERNS = (
    re.compile(r"<[^<>\r\n]{1,128}>"),
    re.compile(r"\[[^\[\]\r\n]{1,128}\]"),
    # Shell prompts are one non-whitespace token (for example root@host:/#).
    # Requiring that shape prevents a partially echoed command such as
    # ``dir slave#flash:/`` from matching at the intermediate ``dir slave#``.
    re.compile(r"[^\s\r\n]{1,160}[$#]"),
)


def strip_terminal_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def detect_terminal_prompt(text: str) -> str:
    normalized = strip_terminal_ansi(text)
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return ""
    candidate = lines[-1]
    for pattern in PROMPT_PATTERNS:
        if pattern.fullmatch(candidate):
            return candidate
    return ""


def incremental_terminal_output(
    buffer: str,
    *,
    buffer_start_cursor: int,
    output_cursor: int,
    requested_cursor: int,
    max_chars: int,
) -> tuple[str, bool]:
    retained_start = max(0, int(buffer_start_cursor))
    retained_end = max(retained_start, int(output_cursor))
    cursor = max(0, int(requested_cursor))
    truncated = cursor < retained_start
    effective_cursor = max(cursor, retained_start)
    offset = min(len(buffer), max(0, effective_cursor - retained_start))
    output = buffer[offset:]
    limit = max(1, int(max_chars))
    if len(output) > limit:
        output = output[-limit:]
        truncated = True
    if effective_cursor > retained_end:
        return "", truncated
    return output, truncated
