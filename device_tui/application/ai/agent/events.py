"""Observable events emitted by the Agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

