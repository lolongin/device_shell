"""Streaming redaction for authentication output split across chunks."""

from __future__ import annotations


class SecretOutputFilter:
    def __init__(self, secrets: tuple[str, ...]) -> None:
        self._secrets = tuple(
            sorted({secret for secret in secrets if secret}, key=len, reverse=True)
        )
        self._max_secret_length = max((len(secret) for secret in self._secrets), default=0)
        self._pending = ""

    def feed(self, text: str) -> str:
        if not self._secrets:
            return text
        combined = self._pending + text
        safe_characters = max(0, len(combined) - self._max_secret_length + 1)
        rendered, consumed = self._render_prefix(combined, safe_characters)
        self._pending = combined[consumed:]
        return rendered

    def flush(self) -> str:
        rendered, _consumed = self._render_prefix(self._pending, len(self._pending))
        self._pending = ""
        return rendered

    def _render_prefix(self, text: str, safe_characters: int) -> tuple[str, int]:
        output: list[str] = []
        index = 0
        while index < safe_characters:
            matched = next(
                (secret for secret in self._secrets if text.startswith(secret, index)),
                None,
            )
            if matched is not None:
                output.append("***")
                index += len(matched)
            else:
                output.append(text[index])
                index += 1
        return "".join(output), index
