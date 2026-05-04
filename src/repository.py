from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, Protocol

try:
    from .api_client import (
        ApiClientError,
        ApiConflictError,
        DeviceApiClient,
        create_http_client_from_env,
    )
    from .data import (
        CURRENT_USER,
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
        Device,
        sample_devices,
    )
except ImportError:
    from api_client import (
        ApiClientError,
        ApiConflictError,
        DeviceApiClient,
        create_http_client_from_env,
    )
    from data import (
        CURRENT_USER,
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
        Device,
        sample_devices,
    )


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

    def toggle_device(self, device_id: str, user: str) -> str:
        ...

    def claim_device(self, device_id: str, user: str) -> str:
        ...

    def release_device(self, device_id: str, user: str) -> str:
        ...

    def current_revision(self) -> int:
        ...

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        ...


class SampleDeviceRepository:
    refresh_interval_seconds = 0.0
    live_update_timeout_seconds = 0.0

    def __init__(self, current_user: str = CURRENT_USER) -> None:
        self._current_user = current_user
        self._devices = sample_devices()

    def current_user(self) -> str:
        return self._current_user

    def fetch_devices(self) -> list[Device]:
        return [replace(device) for device in self._devices]

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

    def current_user(self) -> str:
        return self._api_client.get_current_user()

    def fetch_devices(self) -> list[Device]:
        try:
            payloads = self._api_client.list_devices()
        except ApiClientError as exc:
            raise RepositoryError(str(exc)) from exc
        return [self._map_device(payload) for payload in payloads]

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
        return Device(
            id=str(payload.get("device_id", "")),
            name=str(payload.get("display_name", "")),
            domain=str(payload.get("domain_name", "")),
            device_type=str(payload.get("kind", "")),
            cpu=str(payload.get("cpu_arch", "")),
            status=status,
            owner=occupancy.get("owner"),
            ssh_ip=str(connection.get("ssh_host", "")),
            telnet_ip=str(connection.get("telnet_host", "")),
            username=str(connection.get("username", "")),
            password=str(connection.get("password", "")),
            vendor=str(asset.get("vendor", "")),
            model=str(asset.get("model", "")),
            site=str(asset.get("site", "")),
            rack=str(asset.get("rack", "")),
            version=str(asset.get("version", "")),
            notes=str(payload.get("notes", "")),
            ssh_port=int(connection.get("ssh_port", 22) or 22),
            telnet_port=int(connection.get("telnet_port", 23) or 23),
        )


def create_repository_from_env() -> DeviceRepository:
    source = os.getenv("DEVICE_TUI_DATA_SOURCE", "sample").strip().lower()
    current_user = os.getenv("DEVICE_TUI_CURRENT_USER", CURRENT_USER)
    if source in {"api", "web_api", "stub_api"}:
        refresh_seconds = float(os.getenv("DEVICE_TUI_REFRESH_SECONDS", "30"))
        return ApiDeviceRepository(
            create_http_client_from_env(),
            refresh_interval_seconds=refresh_seconds,
        )
    return SampleDeviceRepository(current_user=current_user)
