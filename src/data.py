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
