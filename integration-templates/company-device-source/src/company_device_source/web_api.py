"""Small company-website interface that proprietary code replaces or implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class CompanyWebApiError(RuntimeError):
    """Safe, user-facing failure returned by the internal website adapter."""


class CompanyWebApiConflict(CompanyWebApiError):
    """The requested occupancy operation conflicts with current remote state."""


@dataclass(frozen=True, slots=True)
class CompanyAuthSession:
    configured: bool
    authenticated: bool
    username: str = ""
    cid: str = ""


@dataclass(frozen=True, slots=True)
class CompanyDevice:
    id: str
    name: str
    domain: str = ""
    device_type: str = "device"
    cpu: str = ""
    status_code: str = "other"
    owner: str | None = None
    board_id: str = ""
    vendor: str = ""
    model: str = ""
    site: str = ""
    rack: str = ""
    version: str = ""
    notes: str = ""
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_username: str = ""
    ssh_password: str = ""
    telnet_host: str = ""
    telnet_port: int = 23
    telnet_username: str = ""
    telnet_password: str = ""
    serial_host: str = ""
    serial_port: int = 23
    serial_username: str = ""
    serial_password: str = ""
    supports_power_off: bool = False
    extra: dict[str, object] = field(default_factory=dict)


class CompanyWebApi(Protocol):
    """Normalized website operations consumed by ``CompanyDeviceRepository``."""

    def auth_status(self) -> CompanyAuthSession: ...
    def login(self, username: str, password: str, cid: str) -> CompanyAuthSession: ...
    def logout(self) -> None: ...
    def list_devices(self) -> list[CompanyDevice]: ...
    def list_owned_device_ids(self) -> set[str]: ...
    def toggle_device(self, device_id: str, user: str) -> str: ...
    def claim_device(self, device_id: str, user: str) -> str: ...
    def release_device(self, device_id: str, user: str) -> str: ...
    def power_off_device(self, device_id: str, user: str) -> str: ...
    def current_revision(self) -> int: ...
    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None: ...
