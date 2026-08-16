from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Device:
    id: str
    name: str
    domain: str
    device_type: str
    cpu: str
    status: str
    owner: str | None
    ssh_ip: str
    telnet_ip: str
    username: str
    password: str
    vendor: str
    model: str
    site: str
    rack: str
    version: str
    notes: str
    board_id: str = ""
    ssh_port: int = 22
    telnet_port: int = 23
    ssh_username: str = ""
    ssh_password: str = ""
    serial_ip: str = ""
    serial_port: int = 23
    serial_username: str = ""
    serial_password: str = ""
    supports_power_off: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def slot_id(self) -> str:
        return str(self.extra.get("slot_id") or self.rack)

    @property
    def board_role(self) -> str:
        return str(self.extra.get("board_role") or self.device_type)

    @property
    def board_type(self) -> str:
        return str(self.extra.get("board_type") or self.model)

    @property
    def subdomain(self) -> str:
        return str(self.extra.get("subdomain") or self.domain)

    @property
    def hardware_platform(self) -> str:
        return str(self.extra.get("hardware_platform") or self.cpu)

    @property
    def serial_server(self) -> str:
        return str(self.extra.get("serial_server") or self.serial_ip)


@dataclass(slots=True)
class SavedServer:
    """A persisted SSH server managed outside the device table."""

    id: str
    name: str
    host: str
    port: int = 22
    username: str = ""
    password: str = ""
    group: str = ""
    notes: str = ""
