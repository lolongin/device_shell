"""Built-in in-memory sample device source."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from ..domain.devices.models import Device
from ..domain.devices.repository import (
    InternalAuthStatus,
    RepositoryConflictError,
    RepositoryError,
)
from ..domain.devices.status import STATUS_IDLE, STATUS_OCCUPIED
from .sample_data import CURRENT_USER, large_sample_devices, sample_devices


class SampleDeviceRepository:
    refresh_interval_seconds = 0.0
    live_update_timeout_seconds = 0.0

    def __init__(
        self,
        current_user: str = CURRENT_USER,
        device_count: int | None = None,
    ) -> None:
        self._current_user = current_user
        self._devices = (
            large_sample_devices(device_count)
            if device_count is not None and device_count > 0
            else sample_devices()
        )

    def current_user(self) -> str:
        return self._current_user

    def internal_auth_status(self) -> InternalAuthStatus:
        return InternalAuthStatus(
            available=False,
            configured=False,
            authenticated=False,
            username=self._current_user,
        )

    def login_internal(
        self,
        username: str,
        password: str,
        cid: str,
    ) -> InternalAuthStatus:
        del username, password, cid
        raise RepositoryError("当前数据源未配置内部网站登录。")

    def logout_internal(self) -> InternalAuthStatus:
        return self.internal_auth_status()

    def fetch_devices(self) -> list[Device]:
        return [replace(device) for device in self._devices]

    def fetch_owned_device_ids(self) -> set[str] | None:
        return {
            device.id
            for device in self._devices
            if device.owner == self._current_user
        }

    def toggle_device(self, device_id: str, user: str) -> str:
        device = self._find_device(device_id)
        if device.owner == user:
            return self.release_device(device_id, user)
        if device.owner is None and device.status == STATUS_IDLE:
            return self.claim_device(device_id, user)
        raise RepositoryConflictError(f"{device.name} is {device.status}")

    def claim_device(self, device_id: str, user: str) -> str:
        device = self._find_device(device_id)
        if device.owner is not None or device.status != STATUS_IDLE:
            raise RepositoryConflictError(f"{device.name} is {device.status}")

        for board in self._find_devices(device_id):
            board.owner = user
            board.status = STATUS_OCCUPIED
            board.extra = dict(board.extra)
            board.extra["occupancy_started_at"] = datetime.now(
                timezone.utc
            ).isoformat()
        return f"Claimed {device.name}"

    def release_device(self, device_id: str, user: str) -> str:
        device = self._find_device(device_id)
        if device.owner != user:
            raise RepositoryConflictError(f"{device.name} is {device.status}")

        for board in self._find_devices(device_id):
            board.owner = None
            board.status = STATUS_IDLE
            board.extra = dict(board.extra)
            for key in (
                "occupied_since",
                "occupied_at",
                "occupancy_started_at",
                "claimed_at",
                "claim_time",
                "owner_since",
                "since",
            ):
                board.extra.pop(key, None)
        return f"Released {device.name}"

    def power_off_device(self, device_id: str, user: str) -> str:
        device = self._find_device(device_id)
        if device.owner != user:
            raise RepositoryConflictError(
                f"{device.name} is not occupied by {user}"
            )
        if not device.supports_power_off:
            raise RepositoryConflictError(
                f"{device.name} does not support power off"
            )
        return f"Powered off {device.name}"

    def _find_device(self, device_id: str) -> Device:
        for device in self._devices:
            if device.id == device_id:
                return device
        raise RepositoryError(f"Unknown device id: {device_id}")

    def _find_devices(self, device_id: str) -> list[Device]:
        devices = [device for device in self._devices if device.id == device_id]
        if not devices:
            raise RepositoryError(f"Unknown device id: {device_id}")
        return devices

    def current_revision(self) -> int:
        return 0

    def wait_for_update(
        self,
        since_revision: int,
        timeout_seconds: float,
    ) -> int | None:
        del since_revision, timeout_seconds
        return None
