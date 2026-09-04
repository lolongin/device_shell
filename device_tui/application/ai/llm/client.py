"""LLM client protocol and common client errors."""

from __future__ import annotations

from typing import Protocol

from .models import LlmResponse


class LlmClientError(RuntimeError):
    """Raised when an LLM request or response cannot be completed."""


class LlmClient(Protocol):
    async def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
    ) -> LlmResponse:
        ...
