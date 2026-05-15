from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, Protocol

from .api_client import ApiClientError, ApiConflictError, DeviceApiClient, ApiNotFoundError
from ._sample_data import (
    CURRENT_USER,
    STATUS_IDLE,
    STATUS_OCCUPIED,
    STATUS_OTHER,
    STATUS_PIPELINE,
    large_sample_devices,
    sample_devices,
)
from .data import Device


class RepositoryError(Exception):
    """Base exception raised by repository implementations."""


class RepositoryConflictError(RepositoryError):
    """Raised when the remote or local state rejects an occupancy change."""


class DeviceRepository(Protocol):
    refresh_interval_seconds: float
    live_update_timeout_seconds: float

    def current_user(self) -> str:
        ...

    def fetch_devices(self) -> list[Device]:
        ...

    def fetch_owned_device_ids(self) -> set[str] | None:
        ...

    def toggle_device(self, device_id: str, user: str) -> str:
        ...

    def claim_device(self, device_id: str, user: str) -> str:
        ...

    def release_device(self, device_id: str, user: str) -> str:
        ...

    def power_off_device(self, device_id: str, user: str) -> str:
        ...

    def current_revision(self) -> int:
        ...

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        ...


class SampleDeviceRepository:
    refresh_interval_seconds = 0.0
    live_update_timeout_seconds = 0.0

    def __init__(self, current_user: str = CURRENT_USER, device_count: int | None = None) -> None:
        self._current_user = current_user
        self._devices = (
            large_sample_devices(device_count)
            if device_count is not None and device_count > 0
            else sample_devices()
        )

    def current_user(self) -> str:
        return self._current_user

    def fetch_devices(self) -> list[Device]:
        return [replace(device) for device in self._devices]

    def fetch_owned_device_ids(self) -> set[str] | None:
        return {device.id for device in self._devices if device.owner == self._current_user}

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

        device.owner = user
        device.status = STATUS_OCCUPIED
        return f"Claimed {device.name}"

    def release_device(self, device_id: str, user: str) -> str:
        device = self._find_device(device_id)
        if device.owner != user:
            raise RepositoryConflictError(f"{device.name} is {device.status}")

        device.owner = None
        device.status = STATUS_IDLE
        return f"Released {device.name}"

    def power_off_device(self, device_id: str, user: str) -> str:
        device = self._find_device(device_id)
        if device.owner != user:
            raise RepositoryConflictError(f"{device.name} is not occupied by {user}")
        if not device.supports_power_off:
            raise RepositoryConflictError(f"{device.name} does not support power off")
        return f"Powered off {device.name}"

    def _find_device(self, device_id: str) -> Device:
        for device in self._devices:
            if device.id == device_id:
                return device
        raise RepositoryError(f"Unknown device id: {device_id}")

    def current_revision(self) -> int:
        return 0

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        return None


class ApiDeviceRepository:
    STATUS_BY_CODE = {
        "occupied": STATUS_OCCUPIED,
        "idle": STATUS_IDLE,
        "pipeline": STATUS_PIPELINE,
        "other": STATUS_OTHER,
    }

    def __init__(self, api_client: DeviceApiClient, refresh_interval_seconds: float = 30.0) -> None:
        self._api_client = api_client
        self.refresh_interval_seconds = refresh_interval_seconds
        self.live_update_timeout_seconds = 25.0
        self._current_user = ""

    def current_user(self) -> str:
        if self._current_user:
            return self._current_user
        try:
            self._current_user = self._api_client.get_current_user()
        except ApiNotFoundError:
            self._current_user = os.getenv("DEVICE_TUI_CURRENT_USER", "")
        return self._current_user

    def fetch_devices(self) -> list[Device]:
        try:
            payloads = self._api_client.list_devices()
        except ApiClientError as exc:
            raise RepositoryError(str(exc)) from exc
        return [self._map_device(payload) for payload in payloads]

    def fetch_owned_device_ids(self) -> set[str] | None:
        try:
            payload = self._api_client.list_my_occupancy()
        except ApiNotFoundError:
            return None
        except ApiClientError as exc:
            raise RepositoryError(str(exc)) from exc
        return self._owned_device_ids_from_payload(payload)

    def _owned_device_ids_from_payload(self, payload: object) -> set[str]:
        if isinstance(payload, list):
            return self._device_ids_from_items(payload)
        if not isinstance(payload, dict):
            return set()

        current_user = payload.get("current_user") or payload.get("user")
        if current_user:
            self._current_user = str(current_user)

        raw_device_ids = payload.get("device_ids") or payload.get("ids")
        if isinstance(raw_device_ids, list):
            return {str(device_id) for device_id in raw_device_ids if str(device_id)}

        raw_devices = payload.get("devices")
        if isinstance(raw_devices, list):
            return self._device_ids_from_items(raw_devices)
        return set()

    def _device_ids_from_items(self, items: list[object]) -> set[str]:
        device_ids: set[str] = set()
        for item in items:
            if isinstance(item, dict):
                device_id = item.get("device_id") or item.get("id")
            else:
                device_id = item
            if device_id:
                device_ids.add(str(device_id))
        return device_ids

    def toggle_device(self, device_id: str, user: str) -> str:
        try:
            response = self._api_client.toggle_device(device_id, user)
        except ApiConflictError as exc:
            raise RepositoryConflictError(str(exc)) from exc
        except ApiClientError as exc:
            raise RepositoryError(str(exc)) from exc
        return str(response.get("message", f"Updated {device_id}"))

    def claim_device(self, device_id: str, user: str) -> str:
        try:
            response = self._api_client.claim_device(device_id, user)
        except ApiConflictError as exc:
            raise RepositoryConflictError(str(exc)) from exc
        except ApiClientError as exc:
            raise RepositoryError(str(exc)) from exc
        return str(response.get("message", f"Claimed {device_id}"))

    def release_device(self, device_id: str, user: str) -> str:
        try:
            response = self._api_client.release_device(device_id, user)
        except ApiConflictError as exc:
            raise RepositoryConflictError(str(exc)) from exc
        except ApiClientError as exc:
            raise RepositoryError(str(exc)) from exc
        return str(response.get("message", f"Released {device_id}"))

    def power_off_device(self, device_id: str, user: str) -> str:
        try:
            response = self._api_client.power_off_device(device_id, user)
        except ApiConflictError as exc:
            raise RepositoryConflictError(str(exc)) from exc
        except ApiClientError as exc:
            raise RepositoryError(str(exc)) from exc
        return str(response.get("message", f"Powered off {device_id}"))

    def current_revision(self) -> int:
        return self._api_client.current_revision()

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        try:
            return self._api_client.wait_for_update(since_revision, timeout_seconds)
        except ApiClientError as exc:
            raise RepositoryError(str(exc)) from exc

    def _map_device(self, payload: dict[str, Any]) -> Device:
        occupancy = payload.get("occupancy", {})
        connection = payload.get("connection", {})
        asset = payload.get("asset", {})
        status_code = str(payload.get("status_code", "other")).lower()
        status = self.STATUS_BY_CODE.get(status_code, str(payload.get("status_label", STATUS_OTHER)))
        legacy_username = str(connection.get("username", ""))
        legacy_password = str(connection.get("password", ""))
        telnet_username = str(connection.get("telnet_username", legacy_username))
        telnet_password = str(connection.get("telnet_password", legacy_password))
        ssh_username = str(connection.get("ssh_username", legacy_username))
        ssh_password = str(connection.get("ssh_password", legacy_password))
        serial_username = str(connection.get("serial_username", telnet_username))
        serial_password = str(connection.get("serial_password", telnet_password))
        capabilities = payload.get("capabilities", {})
        power = payload.get("power", {})
        board_id = (
            payload.get("board_id")
            or payload.get("boardId")
            or payload.get("board")
            or asset.get("board_id")
            or asset.get("boardId")
            or ""
        )
        return Device(
            id=str(payload.get("device_id", "")),
            board_id=str(board_id),
            name=str(payload.get("display_name", "")),
            domain=str(payload.get("domain_name", "")),
            device_type=str(payload.get("kind", "")),
            cpu=str(payload.get("cpu_arch", "")),
            status=status,
            owner=occupancy.get("owner"),
            ssh_ip=str(connection.get("ssh_host", "")),
            telnet_ip=str(connection.get("telnet_host", "")),
            username=telnet_username,
            password=telnet_password,
            vendor=str(asset.get("vendor", "")),
            model=str(asset.get("model", "")),
            site=str(asset.get("site", "")),
            rack=str(asset.get("rack", "")),
            version=str(asset.get("version", "")),
            notes=str(payload.get("notes", "")),
            ssh_port=int(connection.get("ssh_port", 22) or 22),
            telnet_port=int(connection.get("telnet_port", 23) or 23),
            ssh_username=ssh_username,
            ssh_password=ssh_password,
            serial_ip=str(connection.get("serial_host", "")),
            serial_port=int(connection.get("serial_port", 23) or 23),
            serial_username=serial_username,
            serial_password=serial_password,
            supports_power_off=self._truthy(
                capabilities.get("power_off")
                or capabilities.get("powerOff")
                or capabilities.get("can_power_off")
                or power.get("supports_power_off")
                or power.get("power_off")
                or payload.get("supports_power_off")
                or payload.get("can_power_off")
            ),
        )

    @staticmethod
    def _truthy(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on", "support", "supported"}
        return bool(value)


