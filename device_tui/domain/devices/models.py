from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class DeviceFieldDescriptor:
    """Public metadata for a source-provided device field."""

    key: str
    label: str
    kind: Literal["text", "number", "boolean", "datetime", "enum"] = "text"
    group: str = "其他"
    order: int = 100
    searchable: bool = True
    filterable: bool = False
    default_visible: bool = False


@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    """Operations supported by a device, independent of source field names."""

    claim: bool = False
    release: bool = False
    power_off: bool = False
    connect: bool = False


@dataclass(frozen=True, slots=True)
class DeviceRelations:
    parent_id: str | None = None
    children: tuple[str, ...] = ()


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
    # Stable contract fields. Older repositories can omit these and continue
    # using the legacy fields above; source adapters should populate them.
    source: str = "unknown"
    kind: str = "device"
    attributes: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    @property
    def core_source(self) -> str:
        return str(self.source or "").strip() or "unknown"

    @property
    def core_kind(self) -> str:
        return str(self.kind or "").strip() or "device"

    def public_extensions(self) -> dict[str, Any]:
        """Return source additions safe for presentation.

        Legacy ``extra`` values are retained for compatibility, but internal
        flags and credential-like keys never cross the application boundary.
        """
        hidden = {
            "supports_occupancy",
            "imported",
            "temporary",
            "created_at",
            "preferred_kind",
            "shell",
        }
        sensitive_fragments = ("password", "passwd", "token", "cookie", "secret")
        merged: dict[str, Any] = {}
        for values in (self.extra or {}, self.extensions or {}):
            merged.update(
                _safe_public_mapping(
                    values,
                    hidden=hidden,
                    sensitive_fragments=sensitive_fragments,
                )
            )
        return merged

    @property
    def public_attributes(self) -> dict[str, Any]:
        values = self.public_extensions()
        values.update(
            _safe_public_mapping(
                self.attributes or {},
                hidden=set(),
                sensitive_fragments=("password", "passwd", "token", "cookie", "secret"),
            )
        )
        return values

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


def _safe_public_mapping(
    values: dict[str, Any],
    *,
    hidden: set[str],
    sensitive_fragments: tuple[str, ...],
) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in values.items():
        normalized = str(key).strip()
        lowered = normalized.lower()
        if not normalized or normalized in hidden or normalized.startswith("_"):
            continue
        if any(fragment in lowered for fragment in sensitive_fragments):
            continue
        safe[normalized] = value
    return safe


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
