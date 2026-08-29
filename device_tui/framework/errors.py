"""Errors owned by the generic Workflow framework."""

from __future__ import annotations

from typing import Any


class ResourceConflictError(Exception):
    """Raised when a framework resource cannot be acquired."""

    code = "conflict"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


__all__ = ["ResourceConflictError"]
