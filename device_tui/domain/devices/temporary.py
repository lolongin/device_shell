"""Helpers for local-only temporary devices."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .models import Device
from .status import STATUS_IDLE


TEMPORARY_DEVICE_DOMAIN = "临时"
TEMPORARY_DEVICE_TYPE = "Temporary"
TEMPORARY_DEVICE_EXTRA_KEY = "temporary"

_TEMP_ID_PART_RE = re.compile(r"[^A-Za-z0-9]+")


def is_temporary_device(device: Device) -> bool:
    """Return whether a device is managed only in local desktop state."""
    return bool(device.extra.get(TEMPORARY_DEVICE_EXTRA_KEY)) or device.id.startswith("TEMP-")


def make_temporary_device(
    *,
    device_id: str,
    name: str,
    telnet_ip: str,
    telnet_port: int,
    ssh_ip: str,
    ssh_port: int,
    telnet_username: str,
    telnet_password: str,
    ssh_username: str = "",
    ssh_password: str = "",
    serial_ip: str = "",
    serial_port: int = 23,
    serial_password: str = "",
    notes: str = "",
    created_at: str = "",
    preferred_kind: str = "device",
) -> Device:
    created_at = created_at or dt.datetime.now(dt.timezone.utc).isoformat()
    return Device(
        id=device_id,
        name=name,
        domain=TEMPORARY_DEVICE_DOMAIN,
        device_type=TEMPORARY_DEVICE_TYPE,
        cpu="-",
        status=STATUS_IDLE,
        owner=None,
        ssh_ip=ssh_ip,
        telnet_ip=telnet_ip,
        username=telnet_username,
        password=telnet_password,
        vendor="",
        model="",
        site="",
        rack="",
        version="",
        notes=notes,
        ssh_port=ssh_port,
        telnet_port=telnet_port,
        ssh_username=ssh_username,
        ssh_password=ssh_password,
        serial_ip=serial_ip,
        serial_port=serial_port,
        serial_username="",
        serial_password=serial_password,
        supports_power_off=False,
        extra={
            TEMPORARY_DEVICE_EXTRA_KEY: True,
            "created_at": created_at,
            "preferred_kind": preferred_kind if preferred_kind in {"device", "linux", "serial"} else "device",
        },
    )


def next_temporary_device_id(existing_ids: set[str], host: str) -> str:
    """Generate a stable, readable temporary device id."""
    host_part = _TEMP_ID_PART_RE.sub("-", host.strip()).strip("-").upper() or "DEVICE"
    base_id = f"TEMP-{host_part}"
    if base_id not in existing_ids:
        return base_id
    suffix = 2
    while f"{base_id}-{suffix}" in existing_ids:
        suffix += 1
    return f"{base_id}-{suffix}"


def serialize_temporary_device(device: Device) -> dict[str, Any]:
    """Serialize a temporary device for desktop_state.json."""
    return {
        "id": device.id,
        "name": device.name,
        "telnet_ip": device.telnet_ip,
        "telnet_port": device.telnet_port,
        "ssh_ip": device.ssh_ip,
        "ssh_port": device.ssh_port,
        "serial_ip": device.serial_ip,
        "serial_port": device.serial_port,
        "serial_password": device.serial_password,
        "telnet_username": device.username,
        "telnet_password": device.password,
        "ssh_username": device.ssh_username,
        "ssh_password": device.ssh_password,
        "notes": device.notes,
        "created_at": str(device.extra.get("created_at", "")),
        "preferred_kind": str(device.extra.get("preferred_kind", "device")),
    }


def deserialize_temporary_device(payload: object) -> Device | None:
    """Read a temporary device from desktop state, tolerating older payloads."""
    if not isinstance(payload, dict):
        return None
    device_id = str(payload.get("id") or "").strip()
    if not device_id:
        return None
    name = str(payload.get("name") or device_id).strip() or device_id
    telnet_ip = str(payload.get("telnet_ip") or payload.get("telnet_host") or "").strip()
    ssh_ip = str(payload.get("ssh_ip") or payload.get("ssh_host") or "").strip()
    serial_ip = str(payload.get("serial_ip") or payload.get("serial_host") or "").strip()
    legacy_username = str(payload.get("username") or "").strip()
    legacy_password = str(payload.get("password") or "")
    telnet_username = str(payload.get("telnet_username") or legacy_username).strip()
    telnet_password = str(payload.get("telnet_password") or legacy_password)
    ssh_username = str(payload.get("ssh_username") or legacy_username).strip()
    ssh_password = str(payload.get("ssh_password") or legacy_password)
    serial_password = str(payload.get("serial_password") or "")
    notes = str(payload.get("notes") or "")
    created_at = str(payload.get("created_at") or "")
    preferred_kind = str(payload.get("preferred_kind") or "device")
    return make_temporary_device(
        device_id=device_id,
        name=name,
        telnet_ip=telnet_ip,
        telnet_port=_int_or_default(payload.get("telnet_port"), 23),
        ssh_ip=ssh_ip,
        ssh_port=_int_or_default(payload.get("ssh_port"), 22),
        serial_ip=serial_ip,
        serial_port=_int_or_default(payload.get("serial_port"), 23),
        serial_password=serial_password,
        telnet_username=telnet_username,
        telnet_password=telnet_password,
        ssh_username=ssh_username,
        ssh_password=ssh_password,
        notes=notes,
        created_at=created_at,
        preferred_kind=preferred_kind,
    )


def _int_or_default(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
