"""Small utility functions shared across modules."""

from __future__ import annotations

import html

from .data import Device
from ._sample_data import STATUS_OTHER
from .styles import STATUS_COLORS
from .theme_tokens import (
    WORKSPACE_INPUT,
    WORKSPACE_LINE,
    WORKSPACE_MUTED,
    WORKSPACE_NEUTRAL_LINE,
    WORKSPACE_NEUTRAL_SOFT,
    WORKSPACE_SOFT,
    WORKSPACE_SUCCESS_LINE,
    WORKSPACE_SUCCESS_SOFT,
    WORKSPACE_SUCCESS_TEXT,
    WORKSPACE_TEXT,
    WORKSPACE_WARNING_LINE,
    WORKSPACE_WARNING_SOFT,
    WORKSPACE_WARN_TEXT,
)


HTML_BADGE_VARIANTS = {
    "warning": {
        "background": WORKSPACE_WARNING_SOFT,
        "border": WORKSPACE_WARNING_LINE,
        "color": WORKSPACE_WARN_TEXT,
    },
    "success": {
        "background": WORKSPACE_SUCCESS_SOFT,
        "border": WORKSPACE_SUCCESS_LINE,
        "color": WORKSPACE_SUCCESS_TEXT,
    },
    "neutral": {
        "background": WORKSPACE_NEUTRAL_SOFT,
        "border": WORKSPACE_NEUTRAL_LINE,
        "color": WORKSPACE_MUTED,
    },
}

HTML_CHIP_VARIANTS = {
    "filter": {
        "background": WORKSPACE_INPUT,
        "border": WORKSPACE_LINE,
        "color": WORKSPACE_MUTED,
    },
    "neutral": {
        "background": WORKSPACE_NEUTRAL_SOFT,
        "border": WORKSPACE_NEUTRAL_LINE,
        "color": WORKSPACE_MUTED,
    },
}


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
        f"{device.ssh_ip}:{device.ssh_port}" if device.ssh_ip else "",
        device.telnet_ip,
        f"{device.telnet_ip}:{device.telnet_port}" if device.telnet_ip else "",
        device.serial_ip,
        f"{device.serial_ip}:{device.serial_port}" if device.serial_ip else "",
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
    return STATUS_COLORS.get(status, STATUS_COLORS[STATUS_OTHER])


def html_badge(label: str, text: str = "", *, variant: str = "neutral", class_name: str = "") -> str:
    """Render a small OLED workspace badge for Qt rich-text labels."""
    colors = HTML_BADGE_VARIANTS.get(variant, HTML_BADGE_VARIANTS["neutral"])
    class_attr = f" class='{html.escape(class_name, quote=True)}'" if class_name else ""
    body = f"<b>{html.escape(label)}</b>"
    if text:
        body = f"{body} · {html.escape(text)}"
    return (
        f"<div{class_attr} style='margin-top:8px;color:{colors['color']};"
        f"background:{colors['background']};border:1px solid {colors['border']};"
        "border-radius:10px;padding:6px 8px;font-weight:700'>"
        f"{body}</div>"
    )


def html_chip(label: str, value: str = "", *, variant: str = "filter", class_name: str = "") -> str:
    """Render a compact workspace chip for Qt rich-text labels."""
    colors = HTML_CHIP_VARIANTS.get(variant, HTML_CHIP_VARIANTS["neutral"])
    class_attr = f" class='{html.escape(class_name, quote=True)}'" if class_name else ""
    text = html.escape(label)
    if value:
        text = f"{text}: {html.escape(value)}"
    return (
        f"<span{class_attr} style='color:{colors['color']};font-weight:700;"
        f"background:{colors['background']};border:1px solid {colors['border']};"
        "padding:2px 7px;border-radius:999px'>"
        f"{text}</span>"
    )


def html_status_text(text: str, color: str, *, weight: int = 800, class_name: str = "") -> str:
    """Render a short status value for Qt rich-text labels."""
    class_attr = f" class='{html.escape(class_name, quote=True)}'" if class_name else ""
    return (
        f"<span{class_attr} style='color:{html.escape(color, quote=True)};"
        f"font-weight:{weight}'>{html.escape(text)}</span>"
    )


def html_device_summary(
    title: str,
    device_id: str,
    domain: str,
    status: str,
    status_color_value: str,
    owner: str,
    *,
    owner_muted: bool = False,
    detail_html: str = "",
    class_name: str = "",
) -> str:
    """Render the selected-device summary card for Qt rich-text labels."""
    class_attr = f" class='{html.escape(class_name, quote=True)}'" if class_name else ""
    owner_color = WORKSPACE_SOFT if owner_muted else WORKSPACE_MUTED
    return (
        f"<div{class_attr} style='font-size:13px;font-weight:800;color:{WORKSPACE_TEXT}'>"
        f"{html.escape(title)}</div>"
        f"<div style='margin-top:3px;color:{WORKSPACE_MUTED};font-size:11px'>"
        f"{html_status_text(device_id, WORKSPACE_MUTED, weight=700, class_name='device-summary-id')}"
        f" &nbsp;|&nbsp; {html.escape(domain)}"
        " &nbsp;|&nbsp; "
        f"{html_status_text(status, status_color_value, weight=700, class_name='device-summary-status')}"
        " &nbsp;|&nbsp; "
        f"{html_status_text(owner, owner_color, weight=600, class_name='device-summary-owner')}"
        "</div>"
        f"{detail_html}"
    )
