"""Small utility functions shared across modules."""

from __future__ import annotations

from .data import Device
from .styles import STATUS_COLORS


def build_search_text(device: Device) -> str:
    """Build a single searchable string from all device fields."""
    fields = (
        device.board_id,
        device.id,
        device.name,
        device.domain,
        device.device_type,
        device.cpu,
        device.status,
        device.owner or "",
        device.ssh_ip,
        device.telnet_ip,
        device.vendor,
        device.model,
        device.site,
        device.rack,
        device.version,
        device.notes,
    )
    return " ".join(value.lower() for value in fields)


def mask_password(password: str) -> str:
    """Mask a password for display."""
    return "******" if password else ""


def status_color(status: str) -> str:
    """Return a hex colour for the given device status."""
    return STATUS_COLORS.get(status, "#808080")
