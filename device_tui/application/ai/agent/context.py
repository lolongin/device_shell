"""Conversation state owned by a single DeviceAgent interaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentContext:
    conversation_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    device_id: str | None = None
    session_id: str | None = None
    variables: dict[str, Any] = field(default_factory=dict)

