"""Application-control record models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class OperationRecord:
    id: str
    kind: str
    device_id: str
    status: str
    message: str
    created_at: str
    updated_at: str
    data: dict[str, Any] = field(default_factory=dict)
    revision: int = 1
