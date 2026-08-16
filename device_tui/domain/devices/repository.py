"""Repository contracts shared by application services and source plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Device


class RepositoryError(Exception):
    """Base exception raised by repository implementations."""


class RepositoryConflictError(RepositoryError):
    """Raised when a source rejects an occupancy change."""


@dataclass(frozen=True, slots=True)
class InternalAuthStatus:
    available: bool
    configured: bool
    authenticated: bool
    username: str = ""
    cid: str = ""


class DeviceRepository(Protocol):
    refresh_interval_seconds: float
    live_update_timeout_seconds: float

    def internal_auth_status(self) -> InternalAuthStatus: ...

    def login_internal(
        self,
        username: str,
        password: str,
        cid: str,
    ) -> InternalAuthStatus: ...

    def logout_internal(self) -> InternalAuthStatus: ...

    def current_user(self) -> str: ...

    def fetch_devices(self) -> list[Device]: ...

    def fetch_owned_device_ids(self) -> set[str] | None: ...

    def toggle_device(self, device_id: str, user: str) -> str: ...

    def claim_device(self, device_id: str, user: str) -> str: ...

    def release_device(self, device_id: str, user: str) -> str: ...

    def power_off_device(self, device_id: str, user: str) -> str: ...

    def current_revision(self) -> int: ...

    def wait_for_update(
        self,
        since_revision: int,
        timeout_seconds: float,
    ) -> int | None: ...
