"""Stable repository-side types available to external Device TUI plugins.

The application keeps ownership of the concrete data and error implementations;
plugins import them through this public module instead of depending on internal paths.
"""

from device_tui.domain.devices.models import Device
from device_tui.domain.devices.repository import (
    DeviceRepository,
    InternalAuthStatus,
    RepositoryConflictError,
    RepositoryError,
)
from device_tui.domain.devices.status import (
    STATUS_IDLE,
    STATUS_OCCUPIED,
    STATUS_OTHER,
    STATUS_PIPELINE,
)

DEVICE_REPOSITORY_MEMBERS = (
    "refresh_interval_seconds",
    "live_update_timeout_seconds",
    "internal_auth_status",
    "login_internal",
    "logout_internal",
    "current_user",
    "fetch_devices",
    "fetch_owned_device_ids",
    "toggle_device",
    "claim_device",
    "release_device",
    "power_off_device",
    "current_revision",
    "wait_for_update",
)

__all__ = [
    "Device",
    "DEVICE_REPOSITORY_MEMBERS",
    "DeviceRepository",
    "InternalAuthStatus",
    "RepositoryConflictError",
    "RepositoryError",
    "STATUS_IDLE",
    "STATUS_OCCUPIED",
    "STATUS_OTHER",
    "STATUS_PIPELINE",
]
