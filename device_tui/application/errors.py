"""Transport-neutral application errors."""

from __future__ import annotations

from typing import Any


class ApplicationError(Exception):
    """An expected application failure safe to expose through an adapter."""

    code = "application_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class ResourceNotFoundError(ApplicationError):
    code = "resource_not_found"


class ApplicationConflictError(ApplicationError):
    code = "conflict"


class UnsupportedOperationError(ApplicationError):
    code = "unsupported_operation"


class SessionConnectionError(ApplicationError):
    code = "session_connection_error"


class SessionBusyError(ApplicationError):
    code = "session_busy"


class TransferOperationError(ApplicationError):
    code = "transfer_error"


class PackageUpgradeError(ApplicationError):
    code = "package_upgrade_error"
