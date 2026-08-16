"""Persistence-neutral imported device repository."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from threading import RLock
from typing import Protocol

from device_tui.domain.devices.models import Device
from device_tui.domain.devices.repository import InternalAuthStatus, RepositoryError


@dataclass(frozen=True, slots=True)
class ImportedDeviceMetadata:
    source_name: str = ""
    sheet_name: str = ""
    imported_at: str = ""
    row_count: int = 0
    revision: int = 0


class ImportedDeviceStore(Protocol):
    def list_imported_devices(self) -> list[Device]: ...

    def imported_device_metadata(self) -> ImportedDeviceMetadata: ...

    def replace_imported_devices(
        self,
        devices: list[Device],
        *,
        source_name: str,
        sheet_name: str,
        imported_at: str,
    ) -> ImportedDeviceMetadata: ...


def serialize_imported_device(device: Device) -> dict[str, object]:
    payload = asdict(device)
    for key in ("password", "ssh_password", "serial_password"):
        payload[key] = ""
    return payload


def deserialize_imported_device(payload: dict[str, object]) -> Device:
    safe = dict(payload)
    safe["password"] = ""
    safe["ssh_password"] = ""
    safe["serial_password"] = ""
    safe["owner"] = safe.get("owner") or None
    safe["extra"] = dict(safe.get("extra") or {})
    return Device(**safe)  # type: ignore[arg-type]


class MemoryImportedDeviceStore:
    def __init__(self) -> None:
        self._devices: list[Device] = []
        self._metadata = ImportedDeviceMetadata()
        self._lock = RLock()

    def list_imported_devices(self) -> list[Device]:
        with self._lock:
            return [replace(device, extra=deepcopy(device.extra)) for device in self._devices]

    def imported_device_metadata(self) -> ImportedDeviceMetadata:
        with self._lock:
            return self._metadata

    def replace_imported_devices(
        self,
        devices: list[Device],
        *,
        source_name: str,
        sheet_name: str,
        imported_at: str,
    ) -> ImportedDeviceMetadata:
        with self._lock:
            self._devices = [deserialize_imported_device(serialize_imported_device(item)) for item in devices]
            self._metadata = ImportedDeviceMetadata(
                source_name=source_name,
                sheet_name=sheet_name,
                imported_at=imported_at,
                row_count=len(devices),
                revision=self._metadata.revision + 1,
            )
            return self._metadata


class ImportedDeviceRepository:
    refresh_interval_seconds = 0.0
    live_update_timeout_seconds = 0.0

    def __init__(self, store: ImportedDeviceStore) -> None:
        self._store = store

    def current_user(self) -> str:
        return ""

    def internal_auth_status(self) -> InternalAuthStatus:
        return InternalAuthStatus(False, False, False)

    def login_internal(self, username: str, password: str, cid: str) -> InternalAuthStatus:
        del username, password, cid
        raise RepositoryError("Excel/CSV 数据源不需要网站登录。")

    def logout_internal(self) -> InternalAuthStatus:
        return self.internal_auth_status()

    def fetch_devices(self) -> list[Device]:
        return self._store.list_imported_devices()

    def fetch_owned_device_ids(self) -> set[str] | None:
        return set()

    def toggle_device(self, device_id: str, user: str) -> str:
        del device_id, user
        raise RepositoryError("导入设备不支持占用操作。")

    claim_device = toggle_device
    release_device = toggle_device
    power_off_device = toggle_device

    def current_revision(self) -> int:
        return self._store.imported_device_metadata().revision

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        del since_revision, timeout_seconds
        return None
