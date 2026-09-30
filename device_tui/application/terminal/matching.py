"""Terminal output token matching and redaction helpers."""

from __future__ import annotations

import re

from .execution import detect_terminal_prompt


def first_match(
    text: str,
    tokens: tuple[str, ...],
    *,
    case_sensitive: bool,
) -> tuple[str, int] | None:
    best: tuple[str, int] | None = None
    for token in tokens:
        found = match_token(text, token, case_sensitive=case_sensitive)
        if found is not None and (best is None or found[1] < best[1]):
            best = found
    return best


def match_token(
    text: str,
    token: str,
    *,
    case_sensitive: bool,
) -> tuple[str, int] | None:
    if token == "device_prompt":
        prompt = detect_terminal_prompt(text)
        return (prompt, len(text)) if prompt else None
    alias_patterns = {
        "ftp_prompt": r"(?im)(?:^|\n)\s*(?:ftp>|\[ftp\])\s*$",
        "sftp_prompt": r"(?im)(?:^|\n)\s*(?:(?:sftp|sftp-client)>|\[sftp(?:-client)?\])\s*$",
        "username_prompt": r"(?i)(?:(?:user(?:name)?)[ \t]*\([^()\r\n]*(?:\([^()\r\n]*\)[^()\r\n]*)?\)[ \t]*:(?:[ \t]*\([^()\r\n]*\)[ \t]*:)?|(?:user(?:name)?|name|account|login)[^\r\n]{0,200}?):[ \t]*(?=[ \t]*(?:password[ \t]*:[ \t]*)?(?:\r+$|\r+\n|\n|$))",
        "password_prompt": r"(?i)password[ \t]*:[ \t]*(?=\r+$|\r+\n|\n|$)",
        "host_key_prompt": r"(?i)(?:yes/no|continue connecting).{0,80}$",
        "pagination_prompt": r"(?i)(?:----\s*more\s*----|--more--)\s*$",
        "confirmation_prompt": r"(?i)(?:\[y/n\]|\(y/n\)|yes/no)[ \t]*:?[ \t]*(?=\r?$|\r?\n)",
    }
    if token in alias_patterns:
        match = re.search(alias_patterns[token], text)
        return (match.group(0).strip(), match.end()) if match else None
    haystack = text if case_sensitive else text.casefold()
    needle = token if case_sensitive else token.casefold()
    index = haystack.find(needle)
    if index < 0:
        return None
    return token, index + len(token)


def redact_values(text: str, values: tuple[str, ...]) -> str:
    redacted = text
    for value in sorted(set(values), key=len, reverse=True):
        if value:
            redacted = redacted.replace(value, "***")
    return redacted


def secret_ref_requires_redaction(secret_ref: str) -> bool:
    """Usernames are identifiers; passwords and runtime commands are secrets."""
    return not secret_ref.casefold().endswith(".username")
